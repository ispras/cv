#!/usr/bin/env python3

#
# CV is a framework for continuous verification.
#
# Copyright (c) 2018-2023 ISP RAS (http://www.ispras.ru)
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
# pylint: disable=line-too-long

"""
Klever runner - creates a build base, launches Klever and converts results to CVV format.
"""

import json
import os
import re
import shutil
import sys
import time
import argparse

from components.component import Component
from components import *


TAG_BRIDGE = "Bridge"
TAG_KLEVER = "Klever"
TAG_BUILDER = "Builder"
TAG_INSTALL_DIR = "install dir"
TAG_KERNEL_DIR = "kernel dir"
TAG_CIF = "cif"
TAG_WORK_DIR = "work dir"
TAG_CACHE = "cache"
TAG_HOME_DIR = "home dir"
TAG_ARCH = "architecture"
TAG_KLEVER_HOST = "host"
TAG_KLEVER_USER = "user"
TAG_KLEVER_PASS = "pass"
TAG_LAUNCH_CONFIG = "launch config"
TAG_JOB_CONFIG = "job config"
TAG_RESOURCE_CONFIG = "resource config"
TAG_VERIFIER_OPTIONS_CONFIG = "verifier options"
TAG_JOB_ID = "job id"
TAG_PYTHON_VENV = "python-venv"
TAG_BRIDGE_CONFIG = "bridge config"
TAG_DEPLOY_DIR = "deploy dir"
TAG_BUILD_BASE = "build base"
TAG_OUTPUT_DIR = "output dir"
TAG_TASKS_DIR = "tasks dir"
TAG_CONFIG_COMMAND = "config command"

DEFAULT_CONFIG_COMMAND = "allmodconfig"
DEFAULT_ARCH = "x86_64"
BUILDER_SCRIPT = os.path.join("klever", "deploys", "builder.sh")
KLEVER_LAUNCH_SCRIPT = "klever-start-solution"
KLEVER_CHECK_SCRIPT = "klever-download-progress"
DEFAULT_VENV_PATH = "venv/bin"
KLEVER_PROGRESS_FILE = ".klever_progress.json"
BRIDGE_SCRIPT = os.path.join("scripts", "bridge.py")
KLEVER_BUILD_BASE_DIR = "build bases"
COMPONENT_RUNNER = "Runner"
KLEVER_TASKS_DIR = os.path.join("klever-work", "native-scheduler", "scheduler", "tasks")
BUILD_BASE_STORAGE_DIR = "Storage"

BIG_WAIT_INTERVAL = 100
SMALL_WAIT_INTERVAL = 10


class Runner(Component):
    """
    Component for performing full Klever run, which consist of:
    1. Creating of a build base;
    2. Launching klever;
    3. Converting results to CVV.
    """
    def __init__(self, general_config: dict):

        super().__init__(COMPONENT_RUNNER, general_config)
        bridge_config = self.config[TAG_BRIDGE]
        klever_config = self.config[TAG_KLEVER]
        builder_config = self.config[TAG_BUILDER]

        # Builder config
        self.kernel_dir = builder_config.get(TAG_KERNEL_DIR, None)
        self.cif_path = self.__normalize_dir(builder_config.get(TAG_CIF, ""))
        self.builder_work_dir = self.__normalize_dir(builder_config.get(TAG_WORK_DIR, ""))
        self.build_base_cached = self.__normalize_dir(builder_config.get(TAG_CACHE, ""))
        self.arch = builder_config.get(TAG_ARCH, DEFAULT_ARCH)
        self.make_cmd = builder_config.get(TAG_CONFIG_COMMAND, DEFAULT_CONFIG_COMMAND)

        # Klever config
        self.klever_home_dir = self.__normalize_dir(klever_config.get(TAG_HOME_DIR), TAG_HOME_DIR)
        self.klever_deploy_dir = self.__normalize_dir(klever_config.get(TAG_DEPLOY_DIR), TAG_DEPLOY_DIR)
        self.launch_config = self.__normalize_dir(klever_config.get(TAG_LAUNCH_CONFIG), TAG_LAUNCH_CONFIG)
        self.verifier_options_config = self.__normalize_dir(klever_config.get(TAG_VERIFIER_OPTIONS_CONFIG),
                                                            TAG_VERIFIER_OPTIONS_CONFIG)
        self.klever_host = klever_config.get(TAG_KLEVER_HOST)
        self.klever_user = klever_config.get(TAG_KLEVER_USER)
        self.klever_pass = klever_config.get(TAG_KLEVER_PASS)
        self.klever_job_id = klever_config.get(TAG_JOB_ID)
        self.launch_config = self.__normalize_dir(klever_config.get(TAG_LAUNCH_CONFIG), TAG_LAUNCH_CONFIG)
        self.job_config = self.__normalize_dir(klever_config.get(TAG_JOB_CONFIG), TAG_JOB_CONFIG)
        self.resource_config = self.__normalize_dir(klever_config.get(TAG_RESOURCE_CONFIG), TAG_RESOURCE_CONFIG)
        self.python_venv = self.__normalize_dir(klever_config.get(TAG_PYTHON_VENV, ""))

        # Klever Bridge config
        self.bridge_dir = self.__normalize_dir(bridge_config.get(TAG_HOME_DIR), TAG_HOME_DIR)
        self.bridge_config = self.__normalize_dir(bridge_config.get(TAG_BRIDGE_CONFIG), TAG_BRIDGE_CONFIG)
        self.jobs_dir = self.__normalize_dir(bridge_config.get(TAG_WORK_DIR, ""))

    @staticmethod
    def __normalize_dir(dirname: str, fail_with_text="") -> str:
        if dirname:
            if os.path.exists(dirname):
                return os.path.abspath(dirname)
            sys.exit(f"Name '{dirname}' does not exist")
        else:
            if fail_with_text:
                sys.exit(f"Name '{fail_with_text}' was not specified")
            return ""

    def builder(self) -> str:
        """
        Create a build base for specific
        """
        if self.build_base_cached:
            self.logger.info(f"Reusing build base from {self.build_base_cached}")
            return self.build_base_cached
        self.logger.info("Preparing build base")
        builder_script = os.path.join(self.klever_home_dir, BUILDER_SCRIPT)
        cmd = f"{builder_script} --cif {self.cif_path} --kernel-dir {self.kernel_dir} " \
              f"--workdir {self.builder_work_dir} --arch {self.arch} --make {self.make_cmd}"
        if self.command_caller(cmd):
            sys.exit("Cannot build Linux kernel")
        build_base_dir = os.path.join(self.builder_work_dir,
                                      f"build-base-{self.kernel_dir}-{self.arch}-{self.make_cmd}")
        self.logger.info(f"Build base has been prepared in {build_base_dir}")
        return build_base_dir

    def __update_job_config(self, build_base_dir: str):
        with open(self.job_config, errors='ignore', encoding='ascii') as f_jconfig:
            job_config = json.load(f_jconfig)
        with open(self.bridge_config, errors='ignore', encoding='ascii') as f_bconfig:
            bridge_config = json.load(f_bconfig)
        build_base_dir_name = os.path.basename(build_base_dir)
        dst_build_base_dir = os.path.join(self.klever_deploy_dir, KLEVER_BUILD_BASE_DIR, build_base_dir_name)
        if os.path.islink(dst_build_base_dir):
            os.unlink(dst_build_base_dir)
        os.symlink(build_base_dir, dst_build_base_dir)
        job_config[TAG_BUILD_BASE] = build_base_dir_name
        bridge_config[COMPONENT_BENCHMARK_LAUNCHER][TAG_OUTPUT_DIR] = \
            os.path.join(self.klever_deploy_dir, KLEVER_TASKS_DIR)
        bridge_config[COMPONENT_BENCHMARK_LAUNCHER][TAG_TASKS_DIR] = \
            os.path.join(dst_build_base_dir, BUILD_BASE_STORAGE_DIR)
        with open(self.job_config, 'w', encoding='ascii') as f_jconfig:
            json.dump(job_config, f_jconfig, sort_keys=True, indent=4)
        with open(self.bridge_config, 'w', encoding='ascii') as f_bconfig:
            json.dump(bridge_config, f_bconfig, sort_keys=True, indent=4)

    def klever(self, build_base_dir: str) -> str:
        """
        Create a new Klever job and launch it.
        """
        def clear_klever_resources():
            if os.path.exists(KLEVER_PROGRESS_FILE):
                os.unlink(KLEVER_PROGRESS_FILE)
        self.logger.info("Launching Klever tool")
        wall_time_start = time.time()
        self.__update_job_config(build_base_dir)
        credentials = f"--host {self.klever_host} --username {self.klever_user} --password {self.klever_pass}"
        replacement = f"{{\"job.json\": \"{self.job_config}\", \"tasks.json\": \"{self.resource_config}\"," \
                      f"\"verifier profiles.json\": \"{self.verifier_options_config}\"}}"
        cmd = f"{KLEVER_LAUNCH_SCRIPT} {credentials} --rundata {self.launch_config} " \
              f"--replacement '{replacement}' {self.klever_job_id}"
        if self.python_venv:
            os.chdir(self.klever_home_dir)
            if self.command_caller(f"{self.python_venv} -m venv venv"):
                sys.exit("Cannot use python venv")
            sys.path.insert(1, os.path.abspath(DEFAULT_VENV_PATH))
            os.environ["PATH"] += os.pathsep + os.path.abspath(DEFAULT_VENV_PATH)
        launcher_output = self.command_caller_with_output(cmd)
        if not launcher_output:
            sys.exit("Cannot launch Klever")
        res = re.search(r': (.+)', launcher_output)
        if not res:
            sys.exit(f"Cannot obtain new job id from output '{launcher_output}'")
        new_job_id = res.group(1)

        # Wait until job is finished
        time.sleep(BIG_WAIT_INTERVAL)
        clear_klever_resources()
        while True:
            cmd = f"{KLEVER_CHECK_SCRIPT} {credentials} -o {KLEVER_PROGRESS_FILE} {new_job_id}"
            if self.command_caller(cmd):
                sys.exit("Cannot obtain Klever job progress")
            with open(KLEVER_PROGRESS_FILE, errors='ignore', encoding='ascii') as f_progress:
                job_progress = json.load(f_progress)
            if int(job_progress['status']) > 2:
                break
            time.sleep(SMALL_WAIT_INTERVAL)
        clear_klever_resources()
        wall_time_start = round(time.time() - wall_time_start, 3)
        self.logger.info(f"Klever has been successfully completed in {wall_time_start}s")
        return new_job_id

    def bridge(self, new_job_id: str):
        """
        Run Klever Bridge and export solved job into CVV.
        """
        self.logger.info("Exporting results to CVV format via Klever Bridge")
        os.chdir(self.bridge_dir)
        cmd = f"{BRIDGE_SCRIPT} -c {self.bridge_config} -j {new_job_id}"
        self.logger.debug(f"Run Klever Bridge with {cmd}")
        if self.command_caller(cmd):
            sys.exit(f"Cannot export results via Klever Bridge. Reproduce with {cmd}")
        if self.jobs_dir:
            self.logger.info("Clear job files")
            shutil.rmtree(os.path.join(self.jobs_dir, new_job_id))

    def run(self):
        """
        Performs full run.
        """
        build_base_dir = self.builder()
        new_job_id = self.klever(build_base_dir)
        self.bridge(new_job_id)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", help="config file", required=True)

    options = parser.parse_args()
    with open(options.config, errors='ignore', encoding='ascii') as data_file:
        config = json.load(data_file)

    runner = Runner(config)
    runner.run()
