#!/usr/bin/python3

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


def branch_corrector(branch: str):
    return branch.replace("/", "_")


class AutoChecker:
    def __init__(self, config_file: str):
        with open(config_file) as fd:
            config = json.load(fd)
        repository = "https://{}:{}@{}".format(config[TAG_SOURCES][TAG_USERNAME], config[TAG_SOURCES][TAG_PASSWORD],
                                               config[TAG_SOURCES][TAG_REPOSITORY])
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
        logging.basicConfig(format='%(asctime)s: %(name)s: %(levelname)s: %(message)s', level=logger_level,
                            datefmt='%Y-%m-%d %H:%M:%S')
        self.logger = logging.getLogger(name=COMPONENT_AUTO_CHECKER)
        self.logger.setLevel(logger_level)

        self.hostname = None
        self.hostname = self.command_caller("hostname", get_stdout=True)

        # Download repository for the first time
        self.command_caller("rm -rf {}".format(self.source_dir))
        self.command_caller("git clone {} {}".format(repository, self.source_dir))

        self.configs = {}
        for launcher_config in config[TAG_CONFIGS]:
            launcher_config_file = os.path.join(self.work_dir, CONFIGS_DIR, launcher_config + ".json")
            if not os.path.exists(launcher_config_file):
                sys.exit("File {} does not exists".format(launcher_config_file))
            with open(launcher_config_file) as fd:
                tmp = json.load(fd)
            branch = tmp[TAG_BUILDER][TAG_SOURCES][0][TAG_BRANCH]
            if branch in self.configs:
                self.configs.get(branch, []).append(launcher_config_file)
            else:
                self.configs[branch] = [launcher_config_file]

    def get_last_commit_file(self, branch):
        return os.path.join(self.work_dir, BUILDBOT_DIR, "last_checked_commit_{}".format(branch_corrector(branch)))

    def get_last_commit(self, branch: str):
        file = self.get_last_commit_file(branch)
        if os.path.exists(file):
            with open(file) as fd:
                return fd.read().rstrip()
        return None

    def set_last_commit(self, commit: str, branch: str):
        file = self.get_last_commit_file(branch)
        with open(file, "w") as fd:
            fd.write(commit)

    def check_for_new_commits(self, branch: str):
        last_commit = self.command_caller("git rev-parse HEAD", get_stdout=True)
        last_checked_commit = self.get_last_commit(branch)
        is_check = True
        if last_checked_commit:
            is_different = self.command_caller("git diff {}..{}".format(last_checked_commit, last_commit),
                                               get_stdout=True)
            if not is_different:
                self.logger.debug("No differences were found for branch {}".format(branch))
                is_check = False
            else:
                self.logger.debug("New commits were found for branch {}".format(branch))
        else:
            self.logger.debug("Performing initial verification for branch {}".format(branch))
        return is_check, last_checked_commit, last_commit

    def create_temp_configs(self, configs, last_checked_commit, last_commit):
        shutil.rmtree(BUILDBOT_CONFIGS_DIR, ignore_errors=True)
        os.makedirs(BUILDBOT_CONFIGS_DIR)
        temp_configs = []
        for file in configs:
            temp_file = os.path.abspath(os.path.join(BUILDBOT_CONFIGS_DIR, os.path.basename(file)))
            temp_configs.append(temp_file)
            with open(file) as f_old, open(temp_file, "w") as f_new:
                data = json.load(f_old)
                if not last_checked_commit:
                    self.logger.info("Performing initial full verification for {}".format(temp_file))
                else:
                    self.logger.info("Checking commit {} for {}".format(last_commit, temp_file))
                    data[TAG_COMMITS] = ["{}..{}".format(last_checked_commit, last_commit)]
                json.dump(data, f_new, indent=4)
        return temp_configs

    def send_a_message(self, subject, msg):
        subprocess.call("echo \"{}\" | mail -s \"{}\" -r {} {}".
                        format(msg, subject, self.server, " ".join(self.receivers)), shell=True)

    def __get_text(self, branch, last_checked_commit, last_commit, configs, aux=""):
        return "Last commit:\t{}\n" \
               "Last checked commit:\t{}\n" \
               "Branch:\t{}\n" \
               "Host name:\t{}\n" \
               "Configs:\t{}\n" \
               "{}".format(last_commit, last_checked_commit, branch, self.hostname, ", ".join(configs), aux)

    def command_caller(self, cmd: str, get_stdout=False, ignore_errors=False):
        self.logger.debug("Executing command {}".format(cmd))
        try:
            if get_stdout:
                return subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode(errors='ignore').rstrip()
            else:
                subprocess.check_call(cmd, shell=True, stdout=self.output_desc)
        except subprocess.CalledProcessError as e:
            if ignore_errors:
                self.logger.warning("Cannot execute the following command: '{}' due to '{}'".format(cmd, e))
                if get_stdout:
                    return ""
            else:
                self.send_a_message("Failure on automatic checking of new commits",
                                    "Failed command:\t{}\n"
                                    "Host name:\t{}\n"
                                    "Return code:\t{}\n"
                                    "Output:\n{}".format(cmd, self.hostname, e.returncode, e))
                sys.exit(1)

    def __get_new_branches(self, output: str):
        result = set()
        if output:
            for line in output.split("\n"):
                res = re.search(r'\s*\w+\.\.\w+\s+(\S+)\s*->\s*\S+', line)
                if res:
                    branch = res.group(1)
                    result.add(branch)
                    self.logger.debug("Found new commits for branch {}".format(branch))
                res = re.search(r'\s*\[new branch\]\s+(\S+)\s*->\s*\S+', line)
                if res:
                    branch = res.group(1)
                    result.add(branch)
                    self.logger.info("Found new branch {}".format(branch))
        return result

    def loop(self):
        informed_branches = set()
        while True:
            is_empty_run = True
            new_branches = set()
            for branch, configs in self.configs.items():
                os.chdir(self.source_dir)
                self.command_caller("git reset --hard")
                new_branches = new_branches.union(self.__get_new_branches(self.command_caller("git fetch",
                                                                                              get_stdout=True,
                                                                                              ignore_errors=True)))

                if branch in new_branches:
                    new_branches.remove(branch)
                self.command_caller("git checkout {}".format(branch))
                self.command_caller("git reset --hard")
                self.command_caller("git pull origin {}".format(branch), ignore_errors=True)

                is_check, last_checked_commit, last_commit = self.check_for_new_commits(branch)
                os.chdir(self.work_dir)
                if is_check:
                    is_empty_run = False
                    temp_configs = self.create_temp_configs(configs, last_checked_commit, last_commit)
                    self.send_a_message("Starting verification of new commits",
                                        self.__get_text(branch, last_checked_commit, last_commit, configs))
                    log_file = os.path.join(BUILDBOT_CONFIGS_DIR, DEFAULT_LAUNCHER_LOG)
                    self.logger.info("Using log file '{}' for launcher".format(log_file))
                    fd = open(log_file, "w")
                    command = "{} -c {}".format(LAUNCHER_SCRIPT, " ".join(temp_configs))
                    self.logger.debug("Starting launcher via command: '{}'".format(command))
                    exitcode = subprocess.call(command, stderr=fd, stdout=fd, shell=True)
                    fd.close()
                    if exitcode:
                        self.send_a_message("Failure on verification of new commits",
                                            self.__get_text(branch, last_checked_commit, last_commit, configs,
                                                            "Launcher log: {}".format(log_file)))
                        self.logger.error("Stopping verification of branch {} due to failure".format(branch))
                        self.configs.pop(branch, None)
                        break
                    else:
                        self.set_last_commit(last_commit, branch)
                        self.send_a_message("Successful verification of new commits",
                                            self.__get_text(branch, last_checked_commit, last_commit, configs,
                                                            "Launcher log: {}".format(log_file)))
            if not self.configs:
                self.logger.error("Stopping script due to previous failures")
                sys.exit(1)
            new_branches = new_branches - informed_branches
            if new_branches:
                self.send_a_message("Found new untracked commits",
                                    "New commits are not tracked for the following branches: {}".
                                    format(", ".join(new_branches)))
                informed_branches = informed_branches.union(new_branches)
            if is_empty_run:
                self.logger.debug("Sleep for {} seconds".format(self.poll_interval))
                time.sleep(self.poll_interval)


# This script is intended to check specified repository for new commits in accordance with the specified config files.
# If new commits were found, then launcher will start for each config file.
# This script can replace BuildBot.
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", help="auto.json config file", required=True)
    options = parser.parse_args()

    auto_checker = AutoChecker(options.config)
    auto_checker.loop()
