#
# CV is a framework for continuous verification.
#
# Copyright (clade) 2018-2019 ISP RAS (http://www.ispras.ru)
# Ivannikov Institute for System Programming of the Russian Academy of Sciences
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
"""
This component is used for processing source directories (repositories).
"""

import json
import os
import re
import shutil
import subprocess
import sys
import traceback

from components import COMPONENT_BUILDER, TAG_CLADE_CONF, TAG_MAKE_COMMAND, TAG_FAIL_IF_FAILURE, \
    CLADE_BASE_FILE, CLADE_WORK_DIR, TAG_MAKE_CLEAN_COMMAND, TAG_PATH
from components.component import Component

REPOSITORY_GIT = "git"
REPOSITORY_SVN = "svn"
REPOSITORY_NONE = None

REPOSITORY_TYPES = [REPOSITORY_GIT, REPOSITORY_SVN, REPOSITORY_NONE]

TAG_ENVIRON_VARS = "environment variables"
TAG_CLEAN_SOURCES = "clean sources"
DEFAULT_MAKE_CLEAN = "make clean"
TAG_MAKE_TARGET_DIR = "make target dir"
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

    def __init__(self, install_dir, config, source_dir, builder_config=None,
                 repository=REPOSITORY_NONE):
        super().__init__(COMPONENT_BUILDER, config)
        self.install_dir = install_dir
        self.source_dir = source_dir

        if repository not in REPOSITORY_TYPES:
            sys.exit(f"Repository type '{repository}' is not known. "
                     f"Supported types of repositories are: {REPOSITORY_TYPES}")
        self.repository = repository

        if not builder_config:
            self.is_build = False
        else:
            self.is_build = True

        self.clade_conf = builder_config.get(TAG_CLADE_CONF, CLADE_BASIC_CONFIG)

        self.make_command = builder_config.get(TAG_MAKE_COMMAND, DEFAULT_MAKE)
        self.make_clean_command = builder_config.get(TAG_MAKE_CLEAN_COMMAND, DEFAULT_MAKE_CLEAN)
        self.make_target_dir = builder_config.get(TAG_MAKE_TARGET_DIR, "")
        self.fail_if_failure = builder_config.get(TAG_FAIL_IF_FAILURE, True)
        self.clean_sources = builder_config.get(TAG_CLEAN_SOURCES, False)
        self.env = self.component_config.get(TAG_ENVIRON_VARS, {})
        self.env_path = builder_config.get(TAG_PATH, "")
        for name, value in self.env.items():
            os.environ[name] = value

        # Commits range, which should be checked.
        self.start_commit = None
        self.last_commit = None

    def clean(self):
        """
        Clean any changes in a given repository.
        """
        if self.repository:
            self.logger.debug(f"Cleaning the source directory {self.source_dir}")
            os.chdir(self.source_dir)
            if self.clean_sources:
                self.command_caller("rm -rf *")
            if self.repository == REPOSITORY_GIT:
                self.command_caller("git reset --hard")
            elif self.repository == REPOSITORY_SVN:
                self.command_caller("svn revert --recursive .")
            else:
                sys.exit(
                    f"Operation 'clean' is not implemented for repository type '{self.repository}'")
            os.chdir(self.work_dir)

    def change_branch(self, branch: str):
        """
        Use specified branch in a given repository.
        """
        if self.repository:
            self.logger.debug(f"Using branch '{branch}' in the source directory {self.source_dir}")
            os.chdir(self.source_dir)
            if self.repository == REPOSITORY_GIT:
                if self.command_caller(f"git checkout {branch}"):
                    sys.exit(f"Cannot checkout to GIT branch '{branch}' in the source directory")
                self.command_caller("git reset --hard")
            elif self.repository == REPOSITORY_SVN:
                if self.command_caller(f"svn switch ^/{branch}"):
                    sys.exit(f"Cannot switch to SVN branch '{branch}' in the source directory")
                self.command_caller("svn revert --recursive .")
            else:
                sys.exit(f"Operation 'change branch' is not implemented for repository type "
                         f"'{self.repository}'")
            os.chdir(self.work_dir)

    def check_commit(self, commit: str) -> None:
        """
        Use specified commit in a given repository.
        """
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
            sys.exit(f"Operation 'check commit' is not implemented for repository type "
                     f"'{self.repository}'")
        os.chdir(self.work_dir)

    def get_changed_files(self) -> set:
        """
        Find all changed files by a specified range of commits.
        """
        assert self.start_commit
        assert self.last_commit
        result = set()
        os.chdir(self.source_dir)
        if self.repository == REPOSITORY_GIT:
            files = subprocess.check_output(
                f"git diff --name-only {self.start_commit}~1..{self.last_commit}", shell=True)
            for file in files.decode("utf-8", errors="ignore").split():
                result.add(os.path.abspath(file))
        else:
            # TODO: support SVN.
            sys.exit(f"Operation 'get changed files' is not implemented for repository type "
                     f"'{self.repository}'")
        os.chdir(self.work_dir)
        return result

    def get_changed_functions(self) -> set:
        """
        Find all changed functions by a specified range of commits.
        """
        assert self.start_commit
        assert self.last_commit
        result = set()
        os.chdir(self.source_dir)
        if self.repository == REPOSITORY_GIT:
            out = subprocess.check_output(f"git diff --function-context "
                                          f"{self.start_commit}~1..{self.last_commit}", shell=True)
            prev_line = None
            for line in out.splitlines():
                line = line.decode("utf-8", errors="ignore")

                if not prev_line:
                    prev_line = line
                    continue
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
            sys.exit(f"Operation 'get changed functions' is not implemented for repository type "
                     f"'{self.repository}'")
        os.chdir(self.work_dir)
        return result

    def patch(self, patch: str):
        """
        Apply specified patch to the repository.
        """
        os.chdir(self.source_dir)
        if not os.path.exists(patch):
            sys.exit(f"Specified patch '{patch}' does not exists")
        self.logger.debug(f"Applying patch '{patch}' to the source directory {self.source_dir}")
        if self.repository == REPOSITORY_GIT:
            command = f"git apply --ignore-space-change --ignore-whitespace {patch}"
            if self.command_caller(command):
                self.logger.error(f"Command '{command}' failed")
                sys.exit(f"Cannot apply patch '{patch}' to the source directory {self.source_dir}")
        elif self.repository == REPOSITORY_SVN:
            if self.command_caller(f"svn patch {patch}"):
                sys.exit(f"Cannot apply patch '{patch}' to the source directory {self.source_dir}")
        elif not self.repository:
            if self.command_caller(f"patch -lf -p1 < {patch}"):
                sys.exit(f"Cannot apply patch '{patch}' to the source directory {self.source_dir}")
        else:
            sys.exit(f"Operation 'patch' is not implemented for repository type "
                     f"'{self.repository}'")
        os.chdir(self.work_dir)

    def build(self, build_commands_file: str):
        """
        Build repository with a specified command.
        """
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
        if self.make_target_dir:
            os.chdir(self.make_target_dir)
        if self.command_caller(self.make_clean_command):
            self.logger.warning("Make clean failed")

        if os.path.exists(self.env_path):
            os.environ["PATH"] += os.pathsep + self.env_path

        self.logger.debug(f"Using Clade tool to build sources with '{self.make_command}'")
        try:
            # noinspection PyUnresolvedReferences
            from clade import Clade
            clade = Clade(CLADE_WORK_DIR, CLADE_BASE_FILE, conf=self.clade_conf)
            clade.intercept(str(self.make_command).split(), cwd=self.source_dir)
            clade.parse("SrcGraph")
            cmds = clade.compilation_cmds
            for cmd in cmds:
                identifier = cmd['id']
                cmd['command'] = clade.get_cmd_raw(identifier)[0]
                cmd['opts'] = clade.get_cmd_opts(identifier)
            if self.make_target_dir:
                os.chdir(self.source_dir)
            with open(build_commands_file, "w", encoding="utf8") as file_obj:
                json.dump(cmds, file_obj, sort_keys=True, indent="\t")
        except Exception as exception:
            error_msg = f"Building has failed due to {exception}:\n{traceback.format_exc()}"
            if self.fail_if_failure:
                sys.exit(error_msg)
            else:
                self.logger.warning(error_msg)

        os.chdir(self.work_dir)
        self.logger.info("Sources has been successfully built")
