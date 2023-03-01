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

import argparse
import glob
import os
import shutil
import subprocess
import sys

CV_DIR = os.path.dirname(os.path.realpath(sys.argv[0]))
PLUGINS_DIR = os.path.join(CV_DIR, "plugins")
CPA_CONFIG_FILE = "cpa.config"
INSTALL_DIR = os.path.join(CV_DIR, "tools")
MODE_INSTALL = "install"  # default mode - download if needed and build
MODE_BUILD_CUSTOM = "custom"  # custom build with uncommited changes
SCRIPT_MODES = [MODE_INSTALL, MODE_BUILD_CUSTOM]

cpa_configs = {}
is_debug = False


def find_cpa_config() -> list:
    result = [os.path.join(CV_DIR, CPA_CONFIG_FILE)]
    cpa_config_files = glob.glob(os.path.join(PLUGINS_DIR, "*", CPA_CONFIG_FILE))
    cpa_config_files_size = len(cpa_config_files)
    if cpa_config_files_size == 1:
        # Add plugin config
        result.append(cpa_config_files[0])
    if cpa_config_files_size > 1:
        # Several plugins - error.
        sys.exit("Several plugins detected in {} directory, only one is supported!".format(PLUGINS_DIR))
    return result


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("-m", "--mode", default=MODE_INSTALL, choices=SCRIPT_MODES, type=str,
                        help="script mode: install - download if needed and build, "
                             "custom - build with uncommited changes")
    parser.add_argument("-d", "--debug", action='store_true')
    parser.add_argument("-c", "--clear", help="clear existed directory", action='store_true')
    parsed_options = parser.parse_args()

    for cpa_config_file in find_cpa_config():
        with open(cpa_config_file, "r", errors='ignore') as fd:
            for line in fd.readlines():
                line = line.strip()
                if line and not line.startswith("#"):
                    try:
                        (mode, repo, branch, commit) = line.split(";")
                        cpa_configs[mode] = (repo, branch, commit)
                    except ValueError:
                        sys.exit("Wrong format in line '{}'. Correct format is 'mode;repo;branch;commit'".format(line))
    return parsed_options


def command_caller(cmd: str, error_msg: str, cwd=CV_DIR):
    try:
        subprocess.run(cmd, shell=True, cwd=cwd, capture_output=(not is_debug), check=True)
    except subprocess.CalledProcessError as e:
        cmd = str(e.cmd)
        output = e.output.decode("utf-8", errors='ignore').rstrip()
        sys.exit("{}:failed command '{}' error '{}'".format(error_msg, cmd, output))


def __get_tool_dir_name(mode: str) -> str:
    return os.path.join(INSTALL_DIR, mode)


def __is_installed(mode: str) -> bool:
    return os.path.exists(__get_tool_dir_name(mode))


def delete():
    for mode, vals in cpa_configs.items():
        if __is_installed(mode):
            print("Clear directory with tool {}".format(mode))
            shutil.rmtree(__get_tool_dir_name(mode))


def build():
    for mode, vals in cpa_configs.items():
        if __is_installed(mode):
            command_caller("ant build && ant jar", "Cannot build CPAchecker",
                           cwd=__get_tool_dir_name(mode))
            print("Tool {} has successfully been built".format(mode))


def download():
    for mode, vals in cpa_configs.items():
        (repo, branch, commit) = vals
        if not __is_installed(mode):
            command_caller("git clone -b {0} --single-branch {1} {2}".format(branch, repo, __get_tool_dir_name(mode)),
                           "Cannot download CPAchecker")
            print("Tool {} has successfully been downloaded".format(mode))
        else:
            print("Tool {} is already downloaded".format(mode))


def update():
    for mode, vals in cpa_configs.items():
        (repo, branch, commit) = vals
        command_caller("git fetch origin", "Cannot fetch origin", cwd=__get_tool_dir_name(mode))
        command_caller("git checkout {}".format(branch), "Cannot switch branch", cwd=__get_tool_dir_name(mode))
        if commit:
            command_caller("git checkout {}".format(commit), "Cannot checkout commit",
                           cwd=__get_tool_dir_name(mode))
        print("Tool {} has successfully been updated".format(mode))


if __name__ == "__main__":
    options = parse_args()
    is_debug = options.debug
    is_clear = options.clear
    script_mode = options.mode
    if is_clear:
        delete()
    if script_mode == MODE_INSTALL:
        download()
        update()
        build()
    elif script_mode == MODE_BUILD_CUSTOM:
        build()
