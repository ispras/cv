#!/usr/bin/python3
#
# CV is a framework for continuous verification.
#
# Copyright (c) 2018-2019 ISP RAS (http://www.ispras.ru)
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
# pylint: disable=too-few-public-methods

"""
This script is intended to check specified repository for new commits in accordance with the
specified config files. If new commits were found, then launcher will start for each config file.
This script can replace BuildBot.
"""

import argparse
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time

BUILDBOT_DIR = "buildbot"

CONFIGS_DIR = "configs"
BUILDBOT_CONFIGS_DIR = os.path.abspath(os.path.join(BUILDBOT_DIR, CONFIGS_DIR))

TAG_COMMITS = "commits"
TAG_DEBUG = "debug"
TAG_SOURCES = "sources"
TAG_BUILDER = "Builder"
TAG_USERNAME = "username"
TAG_PASSWORD = "password"
TAG_REPOSITORY = "repository"
TAG_PATH = "path"
TAG_POLL_INTERVAL = "poll interval"
TAG_MAIL = "mail"
TAG_SERVER = "server"
TAG_RECEIVERS = "receivers"
TAG_CONFIGS = "configs"
TAG_BRANCH = "branch"

COMPONENT_AUTO_CHECKER = "AutoChecker"
DEFAULT_LAUNCHER_LOG = "launcher.log"

LAUNCHER_SCRIPT = "./scripts/launch.py"


def _branch_corrector(branch: str):
    return branch.replace("/", "_")


class AutoChecker:
    """
    Represents automatic checker of new commits.
    """

    def __init__(self, config_file: str):
        with open(config_file, encoding="ascii") as file_obj:
            config = json.load(file_obj)
        repository = f"https://{config[TAG_SOURCES][TAG_USERNAME]}:" \
                     f"{config[TAG_SOURCES][TAG_PASSWORD]}@" \
                     f"{config[TAG_SOURCES][TAG_REPOSITORY]}"
        self.source_dir = os.path.abspath(config[TAG_SOURCES][TAG_PATH])
        self.work_dir = os.getcwd()
        self.poll_interval = config[TAG_POLL_INTERVAL]
        self.server = config[TAG_MAIL][TAG_SERVER]
        self.receivers = config[TAG_MAIL][TAG_RECEIVERS]
        self.debug = config.get(TAG_DEBUG, False)
        if self.debug:
            self.output_desc = sys.stdout
        else:
            self.output_desc = subprocess.DEVNULL
        logger_level = logging.DEBUG if self.debug else logging.INFO
        logging.basicConfig(format='%(asctime)s: %(name)s: %(levelname)s: %(message)s',
                            level=logger_level, datefmt='%Y-%m-%d %H:%M:%S')
        self.logger = logging.getLogger(name=COMPONENT_AUTO_CHECKER)
        self.logger.setLevel(logger_level)

        self.hostname = None
        self.hostname = self.__command_caller("hostname", get_stdout=True)

        # Download repository for the first time
        self.__command_caller(f"rm -rf {self.source_dir}")
        self.__command_caller(f"git clone {repository} {self.source_dir}")

        self.configs = {}
        for launcher_config in config[TAG_CONFIGS]:
            launcher_config_file = os.path.join(self.work_dir, CONFIGS_DIR,
                                                launcher_config + ".json")
            if not os.path.exists(launcher_config_file):
                sys.exit(f"File {launcher_config_file} does not exists")
            with open(launcher_config_file, encoding="ascii") as file_obj:
                tmp = json.load(file_obj)
            branch = tmp[TAG_BUILDER][TAG_SOURCES][0][TAG_BRANCH]
            if branch in self.configs:
                self.configs.get(branch, []).append(launcher_config_file)
            else:
                self.configs[branch] = [launcher_config_file]

    def __get_last_commit_file(self, branch):
        return os.path.join(self.work_dir, BUILDBOT_DIR,
                            f"last_checked_commit_{_branch_corrector(branch)}")

    def __get_last_commit(self, branch: str):
        file = self.__get_last_commit_file(branch)
        if os.path.exists(file):
            with open(file, encoding="ascii") as file_obj:
                return file_obj.read().rstrip()
        return None

    def __set_last_commit(self, commit: str, branch: str):
        file = self.__get_last_commit_file(branch)
        with open(file, "w", encoding="ascii") as file_obj:
            file_obj.write(commit)

    def __check_for_new_commits(self, branch: str):
        last_commit = self.__command_caller("git rev-parse HEAD", get_stdout=True)
        last_checked_commit = self.__get_last_commit(branch)
        is_check = True
        if last_checked_commit:
            is_different = self.__command_caller(f"git diff {last_checked_commit}..{last_commit}",
                                                 get_stdout=True)
            if not is_different:
                self.logger.debug(f"No differences were found for branch {branch}")
                is_check = False
            else:
                self.logger.debug(f"New commits were found for branch {branch}")
        else:
            self.logger.debug(f"Performing initial verification for branch {branch}")
        return is_check, last_checked_commit, last_commit

    def __create_temp_configs(self, configs, last_checked_commit, last_commit):
        shutil.rmtree(BUILDBOT_CONFIGS_DIR, ignore_errors=True)
        os.makedirs(BUILDBOT_CONFIGS_DIR)
        temp_configs = []
        for file in configs:
            temp_file = os.path.abspath(os.path.join(BUILDBOT_CONFIGS_DIR, os.path.basename(file)))
            temp_configs.append(temp_file)
            with open(file, encoding="ascii") as f_old, \
                    open(temp_file, "w", encoding="ascii") as f_new:
                data = json.load(f_old)
                if not last_checked_commit:
                    self.logger.info(f"Performing initial full verification for {temp_file}")
                else:
                    self.logger.info(f"Checking commit {last_commit} for {temp_file}")
                    data[TAG_COMMITS] = [f"{last_checked_commit}..{last_commit}"]
                json.dump(data, f_new, indent=4)
        return temp_configs

    def __send_a_message(self, subject, msg):
        subprocess.call(f"echo \"{msg}\" | mail -s \"{subject}\" -r {self.server} "
                        f"{' '.join(self.receivers)}", shell=True)

    def __get_text(self, branch, last_checked_commit, last_commit, configs, aux=""):
        return f"Last commit:\t{last_commit}\n" \
               f"Last checked commit:\t{last_checked_commit}\n" \
               f"Branch:\t{branch}\n" \
               f"Host name:\t{self.hostname}\n" \
               f"Configs:\t{', '.join(configs)}\n" \
               f"{aux}"

    def __command_caller(self, cmd: str, get_stdout=False, ignore_errors=False):
        self.logger.debug(f"Executing command {cmd}")
        try:
            if get_stdout:
                return subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT). \
                    decode(errors='ignore').rstrip()
            subprocess.check_call(cmd, shell=True, stdout=self.output_desc)
            return 0
        except subprocess.CalledProcessError as exception:
            if ignore_errors:
                self.logger.warning(
                    f"Cannot execute the following command: '{cmd}' due to '{exception}'")
                if get_stdout:
                    return ""
                return 0
            self.__send_a_message("Failure on automatic checking of new commits",
                                  f"Failed command:\t{cmd}\n"
                                  f"Host name:\t{self.hostname}\n"
                                  f"Return code:\t{exception.returncode}\n"
                                  f"Output:\n{exception}")
            sys.exit(1)

    def __get_new_branches(self, output: str):
        result = set()
        if output:
            for line in output.split("\n"):
                res = re.search(r'\s*\w+\.\.\w+\s+(\S+)\s*->\s*\S+', line)
                if res:
                    branch = res.group(1)
                    result.add(branch)
                    self.logger.debug(f"Found new commits for branch {branch}")
                res = re.search(r'\s*\[new branch]\s+(\S+)\s*->\s*\S+', line)
                if res:
                    branch = res.group(1)
                    result.add(branch)
                    self.logger.info(f"Found new branch {branch}")
        return result

    def loop(self):
        """
        Main loop, in which new commits are checked.
        """
        informed_branches = set()
        while True:
            is_empty_run = True
            new_branches = set()
            for branch, configs in self.configs.items():
                os.chdir(self.source_dir)
                self.__command_caller("git reset --hard")
                new_branches = new_branches.union(self.__get_new_branches(
                    self.__command_caller("git fetch", get_stdout=True, ignore_errors=True)))

                if branch in new_branches:
                    new_branches.remove(branch)
                self.__command_caller(f"git checkout {branch}")
                self.__command_caller("git reset --hard")
                self.__command_caller(f"git pull origin {branch}", ignore_errors=True)

                is_check, last_checked_commit, last_commit = self.__check_for_new_commits(branch)
                os.chdir(self.work_dir)
                if is_check:
                    is_empty_run = False
                    temp_configs = self.__create_temp_configs(configs, last_checked_commit,
                                                              last_commit)
                    self.__send_a_message("Starting verification of new commits",
                                          self.__get_text(branch, last_checked_commit, last_commit,
                                                          configs))
                    log_file = os.path.join(BUILDBOT_CONFIGS_DIR, DEFAULT_LAUNCHER_LOG)
                    self.logger.info(f"Using log file '{log_file}' for launcher")
                    with open(log_file, "w", encoding="ascii") as file_obj:
                        command = f"{LAUNCHER_SCRIPT} -c {' '.join(temp_configs)}"
                        self.logger.debug(f"Starting launcher via command: '{command}'")
                        exitcode = subprocess.call(command, stderr=file_obj, stdout=file_obj,
                                                   shell=True)
                    if exitcode:
                        self.__send_a_message(
                            "Failure on verification of new commits",
                            self.__get_text(branch, last_checked_commit, last_commit, configs,
                                            f"Launcher log: {log_file}"))
                        self.logger.error(
                            f"Stopping verification of branch {branch} due to failure")
                        self.configs.pop(branch, None)
                        break
                    self.__set_last_commit(last_commit, branch)
                    self.__send_a_message(
                        "Successful verification of new commits",
                        self.__get_text(branch, last_checked_commit, last_commit, configs,
                                        f"Launcher log: {log_file}"))
            if not self.configs:
                sys.exit("Stopping script due to previous failures")
            new_branches = new_branches - informed_branches
            if new_branches:
                self.__send_a_message(
                    "Found new untracked commits",
                    f"New commits are not tracked for the following branches: "
                    f"{', '.join(new_branches)}")
                informed_branches = informed_branches.union(new_branches)
            if is_empty_run:
                self.logger.debug(f"Sleep for {self.poll_interval} seconds")
                time.sleep(self.poll_interval)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", help="auto.json config file", required=True)
    options = parser.parse_args()

    auto_checker = AutoChecker(options.config)
    auto_checker.loop()
