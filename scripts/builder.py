#!/usr/bin/python3

import json
import os
import re
import shutil
import subprocess
import sys
import traceback

from component import Component
from config import COMPONENT_BUILDER, TAG_CLADE_CONF, TAG_MAKE_COMMAND, TAG_FAIL_IF_FAILURE, CLADE_BASE_FILE, \
    CLADE_WORK_DIR, TAG_MAKE_CLEAN_COMMAND

REPOSITORY_GIT = "git"
REPOSITORY_SVN = "svn"
REPOSITORY_NONE = None

REPOSITORY_TYPES = [REPOSITORY_GIT, REPOSITORY_SVN, REPOSITORY_NONE]

TAG_ENVIRON_VARS = "environment variables"
TAG_CLEAN_SOURCES = "clean sources"
DEFAULT_MAKE_CLEAN = "make clean"
DEFAULT_MAKE = "make"
CLADE_BASIC_CONFIG = {
  "CC.which_list": [".*?gcc$"],
  "CC.filter_deps": False,
  "Common.filter_in": [".*os$", ".*S$", ".*cc$", ".*a$"],
  "Info.extra CIF opts": ["-DOSMIPS", "-D__MIPSEL__", "-D__mips"]
}


class Builder(Component):
    """
    This component is used for processing source directories (repositories).
    """

    def __init__(self, install_dir, config, source_dir, builder_config={}, repository=REPOSITORY_NONE):
        super(Builder, self).__init__(COMPONENT_BUILDER, config)
        self.install_dir = install_dir
        self.source_dir = source_dir

        if repository not in REPOSITORY_TYPES:
            sys.exit("Repository type '{}' is not known. Supported types of repositories are: {}".
                     format(repository, REPOSITORY_TYPES))
        self.repository = repository

        if not builder_config:
            self.is_build = False
        else:
            self.is_build = True

        self.clade_conf = builder_config.get(TAG_CLADE_CONF, CLADE_BASIC_CONFIG)

        self.make_command = builder_config.get(TAG_MAKE_COMMAND, DEFAULT_MAKE)
        self.make_clean_command = builder_config.get(TAG_MAKE_CLEAN_COMMAND, DEFAULT_MAKE_CLEAN)
        self.fail_if_failure = builder_config.get(TAG_FAIL_IF_FAILURE, True)
        self.clean_sources = builder_config.get(TAG_CLEAN_SOURCES, False)
        self.env = self.component_config.get(TAG_ENVIRON_VARS, {})
        for name, value in self.env.items():
            os.environ[name] = value

        # Commits range, which should be checked.
        self.start_commit = None
        self.last_commit = None

    def clean(self):
        if self.repository:
            self.logger.debug("Cleaning the source directory {}".format(self.source_dir))
            os.chdir(self.source_dir)
            if self.clean_sources:
                self.command_caller("rm -rf *")
            if self.repository == REPOSITORY_GIT:
                self.command_caller("git reset --hard")
            elif self.repository == REPOSITORY_SVN:
                self.command_caller("svn revert --recursive .")
            else:
                sys.exit("Operation 'clean' is not implemented for repository type '{}'".format(self.repository))
            os.chdir(self.work_dir)

    def change_branch(self, branch: str):
        if self.repository:
            self.logger.debug("Using branch '{}' in the source directory {}".format(branch, self.source_dir))
            os.chdir(self.source_dir)
            if self.repository == REPOSITORY_GIT:
                if self.command_caller("git checkout {}".format(branch)):
                    sys.exit("Cannot checkout to GIT branch '{}' in the source directory".format(branch))
                self.command_caller("git reset --hard")
            elif self.repository == REPOSITORY_SVN:
                if self.command_caller("svn switch ^/{}".format(branch)):
                    sys.exit("Cannot switch to SVN branch '{}' in the source directory".format(branch))
                self.command_caller("svn revert --recursive .")
            else:
                sys.exit("Operation 'change branch' is not implemented for repository type '{}'".
                         format(self.repository))
            os.chdir(self.work_dir)

    def check_commit(self, commit: str) -> None:
        os.chdir(self.source_dir)
        if self.repository == REPOSITORY_GIT:
            res = re.search(r'(\w+)\.\.(\w+)', commit)
            if res:
                self.start_commit = res.group(1)
                self.last_commit = res.group(2)
            else:
                self.start_commit = commit
                self.last_commit = commit
            self.command_caller("git reset --hard")
            self.change_branch(self.last_commit)
        else:
            # TODO: support SVN.
            sys.exit("Operation 'check commit' is not implemented for repository type '{}'".format(self.repository))
        os.chdir(self.work_dir)

    def get_changed_files(self) -> set:
        assert self.start_commit
        assert self.last_commit
        result = set()
        os.chdir(self.source_dir)
        if self.repository == REPOSITORY_GIT:
            files = subprocess.check_output("git diff --name-only {0}~1..{1}".format(self.start_commit,
                                                                                     self.last_commit), shell=True)
            for file in files.decode("utf-8", errors="ignore").split():
                result.add(os.path.abspath(file))
        else:
            # TODO: support SVN.
            sys.exit("Operation 'get changed files' is not implemented for repository type '{}'".
                     format(self.repository))
        os.chdir(self.work_dir)
        return result

    def get_changed_functions(self) -> set:
        assert self.start_commit
        assert self.last_commit
        result = set()
        os.chdir(self.source_dir)
        if self.repository == REPOSITORY_GIT:
            out = subprocess.check_output("git diff --function-context {0}~1..{1}".format(self.start_commit,
                                                                                          self.last_commit), shell=True)
            prev_line = None
            for line in out.splitlines():
                line = line.decode("utf-8", errors="ignore")

                if not prev_line:
                    prev_line = line
                    continue
                else:
                    line = prev_line + line
                    prev_line = line.replace(prev_line, "")

                res = re.search(r'@@ (.+) @@(.*)(\W+)(\w+)(\s*)\((\w+)\)', line)  # Macro
                if res:
                    result.add(res.group(4))
                    result.add(res.group(6))
                res = re.search(r'@@ (.+) @@(.*)(\W+)(\w+)(\s*)\((.*)\)', line)  # Function
                if res:
                    result.add(res.group(4))
        else:
            # TODO: support SVN.
            sys.exit("Operation 'get changed functions' is not implemented for repository type '{}'".
                     format(self.repository))
        os.chdir(self.work_dir)
        return result

    def patch(self, patch: str):
        os.chdir(self.source_dir)
        if not os.path.exists(patch):
            sys.exit("Specified patch '{}' does not exists".format(patch))
        self.logger.debug("Applying patch '{}' to the source directory {}".format(patch, self.source_dir))
        if self.repository == REPOSITORY_GIT:
            command = "git apply --ignore-space-change --ignore-whitespace {}".format(patch)
            if self.command_caller(command):
                self.logger.error("Command '{}' failed".format(command))
                sys.exit("Cannot apply patch '{}' to the source directory {}".format(patch, self.source_dir))
        elif self.repository == REPOSITORY_SVN:
            if self.command_caller("svn patch {}".format(patch)):
                sys.exit("Cannot apply patch '{}' to the source directory {}".format(patch, self.source_dir))
        elif not self.repository:
            if self.command_caller("patch -lf -p1 < {}".format(patch)):
                sys.exit("Cannot apply patch '{}' to the source directory {}".format(patch, self.source_dir))
        else:
            sys.exit("Operation 'patch' is not implemented for repository type '{}'".format(self.repository))
        os.chdir(self.work_dir)

    def build(self, build_commands_file: str):
        if not self.is_build:
            return
        os.chdir(self.source_dir)

        # Remove Clade working directory and temporary files
        tmp_path = os.path.join(self.source_dir, CLADE_WORK_DIR)
        if os.path.exists(tmp_path):
            shutil.rmtree(tmp_path)
        tmp_path = os.path.join(self.source_dir, CLADE_BASE_FILE)
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        if self.command_caller(self.make_clean_command):
            self.logger.warning("Make clean failed")

        self.logger.debug("Using Clade tool to build sources with '{}'".format(self.make_command))
        try:
            from clade import Clade
            c = Clade(CLADE_WORK_DIR, CLADE_BASE_FILE, conf=self.clade_conf)
            c.intercept(str(self.make_command).split())
            c.parse("SrcGraph")
            cmds = c.compilation_cmds
            for cmd in cmds:
                identifier = cmd['id']
                cmd['command'] = c.get_cmd_raw(identifier)[0]
                cmd['opts'] = c.get_cmd_opts(identifier)
            with open(build_commands_file, "w") as fd:
                json.dump(cmds, fd, sort_keys=True, indent=4)
        except Exception:
            error_msg = "Building has failed due to: {}".format(traceback.format_exc())
            if self.fail_if_failure:
                sys.exit(error_msg)
            else:
                self.logger.warning(error_msg)

        os.chdir(self.work_dir)
        self.logger.info("Sources has been successfully built")


'''
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", "-i", help="install directory", default=os.path.abspath(DEFAULT_INSTALL_DIR))
    parser.add_argument("--config", "-c", help="config file", required=True)
    parser.add_argument("--sources", "-s", help="sources directory", required=True)
    parser.add_argument("--patch", "-p", help="patch for building")

    options = parser.parse_args()
    with open(options.config) as fd:
        config = json.load(fd)

    builder = Builder(options.install, config, options.sources)
    builder.clean()
    builder.patch(options.patch)
    builder.build()
'''
