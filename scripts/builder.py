#!/usr/bin/python3

import argparse
import json
import os
import shutil
import sys

from component import Component
from config import CLADE_CC, CLADE_INTERCEPT, DEFAULT_BUILD_COMMANDS_FILE, COMPONENT_BUILDER, TAG_CLADE_CONF, \
    TAG_MAKE_COMMAND, TAG_FAIL_IF_FAILURE, CLADE_BASE_FILE, CLADE_DEFAULT_CONFIG_FILE, CLADE_WORK_DIR

TAG_ENVIRON_VARS = "environment variables"
TAG_CLEAN_SOURCES = "clean sources"
DEFAULT_INSTALL_DIR = "tools"
DEFAULT_MAKE_CLEAN = "make clean"
CLADE_BASIC_CONFIG = {
  "CC.which_list": [".*?gcc$"],
  "CC.filter_deps": False,
  "Common.filter_in": [".*os$", ".*S$", ".*cc$", ".*a$"],
  "Info.extra CIF opts": ["-DOSMIPS", "-D__MIPSEL__", "-D__mips"]
}


class Builder(Component):
    def __init__(self, install_dir, config, source_dir):
        super(Builder, self).__init__(COMPONENT_BUILDER, config)
        self.install_dir = install_dir
        self.source_dir = source_dir

        self.clade_conf = self.component_config.get(TAG_CLADE_CONF, None)
        if self.clade_conf:
            if not os.path.exists(self.clade_conf):
                sys.exit("Specified clade config file '{}' does not exist".format(self.clade_conf))
        else:
            with open(CLADE_DEFAULT_CONFIG_FILE, "w") as fd:
                json.dump(CLADE_BASIC_CONFIG, fd, sort_keys=True, indent=4)
            self.clade_conf = os.path.join(os.getcwd(), CLADE_DEFAULT_CONFIG_FILE)

        self.make_command = self.component_config.get(TAG_MAKE_COMMAND, "make")
        self.fail_if_failure = self.component_config.get(TAG_FAIL_IF_FAILURE, True)
        self.clean_sources = self.component_config.get(TAG_CLEAN_SOURCES, False)
        self.env = self.component_config.get(TAG_ENVIRON_VARS, {})

    def clean(self):
        self.logger.debug("Clear the source directory")
        os.chdir(self.source_dir)
        if self.clean_sources:
            self.command_caller("rm -rf *")
        self.command_caller("git reset --hard")
        os.chdir(self.work_dir)

    def change_branch(self, branch: str):
        self.logger.debug("Using branch '{}' in the source directory".format(branch))
        os.chdir(self.source_dir)
        if self.command_caller("git checkout {}".format(branch)):
            sys.exit("Cannot checkout to branch '{}' in the source directory".format(branch))
        self.command_caller("git reset --hard")
        os.chdir(self.work_dir)

    def patch(self, patch: str):
        os.chdir(self.source_dir)
        if not os.path.exists(patch):
            sys.exit("Specified patch '{}' does not exists".format(patch))
        self.logger.debug("Applying patch '{}' to the source directory".format(patch))
        command = "git apply --ignore-space-change --ignore-whitespace {}".format(patch)
        if self.command_caller(command):
            self.logger.error("Command '{}' failed".format(command))
            sys.exit("Cannot apply patch '{}' to the source directory {}".format(patch, self.source_dir))
        os.chdir(self.work_dir)

    def build(self):
        os.chdir(self.source_dir)
        build_commands_file = os.path.join(self.work_dir, DEFAULT_BUILD_COMMANDS_FILE)

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
