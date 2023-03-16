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
PLUGINS_DIR = os.path.join(CV_DIR, "plugin")
CPA_CONFIG_FILE = "cpa.config"
INSTALL_DIR = os.path.join(CV_DIR, "tools")
PATCH_DIR = os.path.join("patches", "tools", "cpachecker")
DEPLOY_DIR = "tools"
MODE_INSTALL = "install"  # default mode - download if needed and build
MODE_BUILD_CUSTOM = "custom"  # custom build with uncommited changes
MODE_DOWNLOAD = "download"
MODE_BUILD = "build"
MODE_CLEAN = "clean"
SCRIPT_MODES = [MODE_INSTALL, MODE_BUILD_CUSTOM, MODE_DOWNLOAD, MODE_BUILD, MODE_CLEAN]
CPA_WILDCARD_ARCH = "CPAchecker-*.tar.bz2"
CPA_WILDCARD_DIR = "CPAchecker-*/"
CPA_ARCH = "build.tar.bz2"

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
                             "custom - build with uncommited changes, download, build, clean")
    parser.add_argument("-i", "--install-dir", type=str, dest="install_dir", help="path to install directory")
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


def command_caller(cmd: str, error_msg: str, cwd=CV_DIR, is_check=True):
    try:
        if is_debug:
            stdout = None
        else:
            stdout = subprocess.PIPE
        subprocess.run(cmd, shell=True, cwd=cwd, check=True, stdout=stdout)
    except subprocess.CalledProcessError as e:
        cmd = str(e.cmd)
        error_str = "{}: failed command '{}'".format(error_msg, cmd)
        if e.output:
            output = e.output.decode("utf-8", errors='ignore').rstrip()
            error_str = "{}, error: {}".format(error_str, output)
        if is_check:
            sys.exit(error_str)
        else:
            print(error_str)


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
            command_caller("ant build dist-unix-tar", "Cannot build CPAchecker",
                           cwd=__get_tool_dir_name(mode))
            try:
                cpa_arch_old = glob.glob(os.path.join(__get_tool_dir_name(mode), CPA_WILDCARD_ARCH))[0]
                cpa_arch_new = os.path.join(__get_tool_dir_name(mode), CPA_ARCH)
                os.rename(cpa_arch_old, cpa_arch_new)
            except ValueError:
                sys.exit("Cannot find CPAchecker build arch for mode {}".format(mode))
            print("Tool {} has successfully been built".format(mode))


def deploy(deploy_dir: str):
    if not deploy_dir or not os.path.exists(deploy_dir):
        sys.exit("Deploy directory {} does not exist".format(deploy_dir))
    for mode, vals in cpa_configs.items():
        deploy_dir_full = os.path.join(deploy_dir, DEPLOY_DIR, mode)
        tools_dir_full = os.path.join(deploy_dir, DEPLOY_DIR)
        if __is_installed(mode):
            cpa_arch = os.path.join(__get_tool_dir_name(mode), CPA_ARCH)
            command_caller("tar -xf {}".format(cpa_arch), "Cannot extract build arch", cwd=__get_tool_dir_name(mode))
            os.makedirs(tools_dir_full, exist_ok=True)
            command_caller("rm -rf {}".format(deploy_dir_full), "Cannot clear old deploy directory")
            try:
                cpa_dir_old = glob.glob(os.path.join(__get_tool_dir_name(mode), CPA_WILDCARD_DIR))[0]
                shutil.move(cpa_dir_old, deploy_dir_full)
            except ValueError:
                sys.exit("Cannot find CPAchecker build arch for mode {}".format(mode))
        print("Tool {} has successfully been deployed into {}".format(mode, deploy_dir_full))


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

        command_caller("git reset --hard", "Cannot reset branch", cwd=__get_tool_dir_name(mode))
        command_caller("git clean -f", "Cannot clean repository", cwd=__get_tool_dir_name(mode))
        command_caller("git fetch origin", "Cannot fetch origin", cwd=__get_tool_dir_name(mode))
        command_caller("git checkout {}".format(branch), "Cannot switch branch", cwd=__get_tool_dir_name(mode))
        if commit:
            command_caller("git checkout {}".format(commit), "Cannot checkout commit",
                           cwd=__get_tool_dir_name(mode))
        patches = [os.path.join(CV_DIR, PATCH_DIR, "{}.patch".format(mode))] + \
                  glob.glob(os.path.join(PLUGINS_DIR, "*", PATCH_DIR, "{}.patch".format(mode)))
        for patch in patches:
            if not os.path.exists(patch):
                print("Patch {} does not exist".format(patch))
                continue
            print("Applying patch {} for tool {}".format(patch, mode))
            command_caller("git apply --ignore-space-change --ignore-whitespace {}".format(patch),
                           "Cannot apply patch", cwd=__get_tool_dir_name(mode), is_check=False)
        print("Tool {} has successfully been updated".format(mode))


if __name__ == "__main__":
    options = parse_args()
    is_debug = options.debug
    is_clear = options.clear
    script_mode = options.mode
    install_dir = options.install_dir
    if script_mode == MODE_INSTALL:
        if not install_dir or not os.path.exists(install_dir):
            sys.exit("Deploy directory was not specified")
    if is_clear or script_mode == MODE_CLEAN:
        delete()
    if script_mode == MODE_CLEAN:
        exit(0)
    download()
    if script_mode == MODE_DOWNLOAD:
        exit(0)
    if not script_mode == MODE_BUILD_CUSTOM:
        update()
    build()
    if script_mode == MODE_BUILD:
        exit(0)
    deploy(install_dir)
