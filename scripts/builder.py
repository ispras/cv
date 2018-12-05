#!/usr/bin/python3

import json
import os
import shutil
import sys

from component import Component
from config import CLADE_CC, CLADE_INTERCEPT, COMPONENT_BUILDER, TAG_CLADE_CONF, \
    TAG_MAKE_COMMAND, TAG_FAIL_IF_FAILURE, CLADE_BASE_FILE, CLADE_DEFAULT_CONFIG_FILE, CLADE_WORK_DIR

REPOSITORY_GIT = "git"
REPOSITORY_SVN = "svn"
REPOSITORY_NONE = None

REPOSITORY_TYPES = [REPOSITORY_GIT, REPOSITORY_SVN, REPOSITORY_NONE]

TAG_ENVIRON_VARS = "environment variables"
TAG_CLEAN_SOURCES = "clean sources"
DEFAULT_MAKE_CLEAN = "make clean"
CLADE_BASIC_CONFIG = {
  "CC.which_list": [".*?gcc$"],
  "CC.filter_deps": False,
  "Common.filter_in": [".*os$", ".*S$", ".*cc$", ".*a$"],
  "Info.extra CIF opts": ["-DOSMIPS", "-D__MIPSEL__", "-D__mips"]
}


class Builder(Component):
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

        self.clade_conf = builder_config.get(TAG_CLADE_CONF, None)
        if self.clade_conf:
            if not os.path.exists(self.clade_conf):
                sys.exit("Specified clade config file '{}' does not exist".format(self.clade_conf))
        else:
            with open(CLADE_DEFAULT_CONFIG_FILE, "w") as fd:
                json.dump(CLADE_BASIC_CONFIG, fd, sort_keys=True, indent=4)
            self.clade_conf = os.path.join(os.getcwd(), CLADE_DEFAULT_CONFIG_FILE)

        self.make_command = builder_config.get(TAG_MAKE_COMMAND, "make")
        self.fail_if_failure = builder_config.get(TAG_FAIL_IF_FAILURE, True)
        self.clean_sources = builder_config.get(TAG_CLEAN_SOURCES, False)
        self.env = self.component_config.get(TAG_ENVIRON_VARS, {})

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
        if self.runexec_wrapper(DEFAULT_MAKE_CLEAN):
            self.logger.warning("Make clean failed")

        self.logger.debug("Using Clade tool to build sources with '{}'".format(self.make_command))
        log_file = os.path.join(self.work_dir, "builder.log")
        for var, value in self.env.items():
            os.environ[var] = value
        if self.runexec_wrapper("{} {}".format(CLADE_INTERCEPT, self.make_command), output_file=log_file):
            error_msg = "Building has failed. See details in '{}'".format(log_file)
            if self.fail_if_failure:
                sys.exit(error_msg)
            else:
                self.logger.warning(error_msg)

        log_file = os.path.join(self.work_dir, "clade.log")
        clade_cc_cmd = "{} -w {} -c {} {}".format(CLADE_CC, CLADE_WORK_DIR, self.clade_conf, CLADE_BASE_FILE)
        if self.runexec_wrapper(clade_cc_cmd, output_file=log_file):
            sys.exit("Clade has failed. See details in '{}'".format(log_file))
        shutil.copy(os.path.join(CLADE_WORK_DIR, "CC", "cmds.json"), build_commands_file)
        os.chdir(self.work_dir)
        self.logger.info("Sources has been successfully built")


# TODO: not supported anymore.
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
