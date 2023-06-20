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

"""
Class for representation of an arbitrary component.
"""

import json
import logging
import os
import re
import resource
import subprocess
import sys
import tempfile
import time

from components import TAG_DIRS, TAG_DEBUG, TAG_TOOLS, BENCHEXEC, DEFAULT_INSTALL_DIR, \
    TAG_MEMORY_USAGE, TAG_CPU_TIME, TAG_WALL_TIME, TAG_LOG_FILE

DEFAULT_MEMORY_LIMIT = "3GB"
TAG_RUNEXEC = "runexec"
TOOL_CONFIG_FILE = os.path.join(DEFAULT_INSTALL_DIR, "config.json")
TAG_DEFAULT_TOOL_PATH = "default tool path"


class Component:
    """
    Class for representation of an arbitrary component.
    """

    tools_config = {}

    @staticmethod
    def _get_tool_default_path(tool_name: str):
        default_tool_path = Component.tools_config[TAG_DEFAULT_TOOL_PATH]
        if tool_name not in default_tool_path:
            sys.exit(f"Path for {tool_name} is not defined in config file {TOOL_CONFIG_FILE}")
        return default_tool_path[tool_name]

    def __init__(self, name: str, config: dict):
        self.start_time = time.time()
        self.start_cpu_time = time.process_time()
        self.memory = 0
        self.cpu_time = 0.0
        self.name = name
        self.work_dir = os.path.abspath(os.getcwd())

        # Config.
        self.config = config
        self.runexec = self.config.get(TAG_RUNEXEC, True)
        self.__propagate_config()

        # Debug and logging.
        self.debug = self.component_config.get(TAG_DEBUG, False)
        logger_level = logging.DEBUG if self.debug else logging.INFO
        logging.basicConfig(format='%(name)s: %(levelname)s: %(message)s', level=logger_level)
        self.logger = logging.getLogger(name=self.name)
        self.logger.setLevel(logger_level)

        # Should be rewritten.
        self.install_dir = None
        self.error_logs = set()
        self.temp_logs = set()
        if not Component.tools_config:
            install_dir = os.path.abspath(
                os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir, os.pardir)
            )
            with open(os.path.join(install_dir, TOOL_CONFIG_FILE), encoding='ascii') as file_obj:
                Component.tools_config = json.load(file_obj)

    def __propagate_config(self):
        """
        Propagate config for a given component (some general option can be overriden in
        component config).
        """
        component_config = self.config.get(self.name, {})
        for tag in [TAG_DIRS, TAG_DEBUG, TAG_TOOLS]:
            if tag in self.config and tag not in component_config:
                component_config[tag] = self.config[tag]
        self.component_config = component_config

    def runexec_wrapper(self, cmd, output_dir=None, output_file=None):
        """
        Call a command inside RunExec tool, track its resources and redirect its output into
        log file. Note, it produces some overheads.
        :param cmd: a command to be run (as a string).
        :param output_dir: a directory, in which log files will be placed (if None,
        then stdout will be used).
        :param output_file: use specified path for output.
        :return: exit code of a command.
        """
        if not self.runexec:
            return self.command_caller(cmd)
        path_to_benchexec = self.get_tool_path(self._get_tool_default_path(BENCHEXEC))
        os.environ["PATH"] += os.pathsep + path_to_benchexec

        if not output_file:
            if not output_dir:
                # redirect into console
                file_object, path = tempfile.mkstemp(suffix=".log")
            else:
                file_object, path = tempfile.mkstemp(dir=output_dir, suffix=".log")
            os.close(file_object)
        else:
            path = output_file

        try:
            if isinstance(cmd, list):
                out = subprocess.check_output(
                    ["runexec", "--output", path, "--memlimit", DEFAULT_MEMORY_LIMIT, "--"] + cmd,
                    stderr=subprocess.STDOUT)
            elif isinstance(cmd, str):
                out = subprocess.check_output(
                    f"runexec --output {path} --memlimit {DEFAULT_MEMORY_LIMIT} -- {cmd}",
                    stderr=subprocess.STDOUT, shell=True)
            else:
                raise TypeError(f"Unsupported type of command '{cmd}'")
        except subprocess.CalledProcessError as exception:
            cmd = str(exception.cmd)
            output = exception.output.decode("utf-8", errors='ignore').rstrip()
            sys.exit(f"RunExec has failed on command '{cmd}' due to '{output}'")
        exitcode = 0
        memory = 0
        cpu_time = 0.0

        for line in out.splitlines():
            line = line.decode("utf-8", errors='ignore')
            res = re.search(r'exitcode=(\d+)', line)
            if res:
                exitcode = int(res.group(1))
            res = re.search(r'cputime=(.+)s', line)
            if res:
                cpu_time = float(res.group(1))
            res = re.search(r'memory=(\d+)', line)
            if res:
                memory = round(int(res.group(1)))
        self.cpu_time += cpu_time
        self.memory = max(memory, self.memory)

        if not output_dir:
            # Put output into the console.
            if self.debug and exitcode:
                with open(path, "r", errors='ignore', encoding='utf8') as file_object:
                    self.logger.info(f"Command '{cmd}' output")
                    for line in file_object.readlines():
                        print(line)
                if os.path.exists(path):
                    os.remove(path)
        else:
            if exitcode and path:
                self.error_logs.add(path)

        return exitcode

    def command_caller_with_output(self, cmd: str) -> str:
        """
        Execute command and return output.
        """
        self.logger.debug(f"Executing command {cmd}")
        try:
            return subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).\
                decode(errors='ignore').rstrip()
        except subprocess.CalledProcessError as exception:
            self.logger.debug(f"Cannot execute command '{cmd}' due to {exception}")
            return ""

    def command_caller(self, cmd, output_dir=None, keep_log=True) -> int:
        """
        Call a command and redirect its output into log file.
        :param cmd: a command to be run.
        :param output_dir: a directory, in which log files will be placed
        (if None, then stdout will be used).
        :param keep_log: print logs in case of command failure.
        :return: exit code of a command.
        """

        if not output_dir:
            # redirect into console
            file_object, path = sys.stdout, None
            if not self.debug:
                file_object = subprocess.DEVNULL
        else:
            file_object, path = tempfile.mkstemp(dir=output_dir, suffix=".log")
        if isinstance(cmd, list):
            exitcode = subprocess.call(cmd, stderr=file_object, stdout=file_object)
        elif isinstance(cmd, str):
            exitcode = subprocess.call(cmd, stderr=file_object, stdout=file_object, shell=True)
        else:
            raise TypeError(f"Unsupported command '{cmd}'")
        if output_dir:
            os.close(file_object)
        if exitcode and path:
            if keep_log:
                self.error_logs.add(path)
            else:
                self.temp_logs.add(path)
            with open(path, "a", encoding='utf8') as file_object:
                if isinstance(cmd, list):
                    cmd_str = " ".join(cmd)
                else:
                    cmd_str = cmd
                file_object.write(f"\nCommand: '{cmd_str}'")

        if self.debug and exitcode and path:
            with open(path, "r", errors='ignore', encoding='utf8') as file_object:
                self.logger.info(f"Command '{cmd}' output")
                for line in file_object.readlines():
                    print(line)

        return exitcode

    def exec_sed_cmd(self, regexp, file, args=""):
        """
        Execute sed command with the given arguments.
        """
        sed_cmd = f"sed -i {args} '{regexp}' {file}"
        if self.command_caller(sed_cmd):
            self.logger.warning("Can not execute sed command: '%s'", sed_cmd)

    def get_tool_path(self, default_path, abs_path=None, all_paths=False):
        """
        Get absolute path for a specified tool.
        """
        assert self.install_dir
        if abs_path and os.path.isabs(abs_path) and os.path.exists(abs_path):
            # Take absolute path from the config file.
            result_path = abs_path
        else:
            # Take default path.
            if isinstance(default_path, list):
                results_path = []
                for path in default_path:
                    result_path = os.path.abspath(os.path.join(self.install_dir, path))
                    if os.path.exists(result_path):
                        results_path.append(result_path)
                        if not all_paths:
                            break
                if not all_paths:
                    if not results_path:
                        sys.exit(f"Tool paths {default_path} do not exist")
                    return results_path[0]
                return results_path
            result_path = os.path.abspath(os.path.join(self.install_dir, default_path))
        return result_path

    def get_component_full_stats(self):
        """
        Gets component resource consumptions based on overall process information.
        """
        wall_time = time.time() - self.start_time
        self.memory = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024 + \
            int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss) * 1024
        self.cpu_time = float(resource.getrusage(resource.RUSAGE_SELF).ru_utime +
                              resource.getrusage(resource.RUSAGE_SELF).ru_stime +
                              resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime +
                              resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime)
        self.logger.debug(f"Wall time: {round(wall_time, 2)}s")
        self.logger.debug(f"CPU time: {round(self.cpu_time, 2)}s")
        self.logger.debug(f"Memory usage: {round(self.memory / (2**20), 2)}Mb")
        return {
            TAG_MEMORY_USAGE: self.memory,
            TAG_CPU_TIME: self.cpu_time,
            TAG_WALL_TIME: wall_time,
            TAG_LOG_FILE: self.error_logs
        }

    def get_component_stats(self):
        """
        Gets component resource consumptions based on RunExec calls.
        """
        wall_time = time.time() - self.start_time
        self.cpu_time += time.process_time() - self.start_cpu_time
        self.memory += int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
        self.logger.debug(f"Wall time: {round(wall_time, 2)}s")
        self.logger.debug(f"CPU time: {round(self.cpu_time, 2)}s")
        self.logger.debug(f"Memory usage: {round(self.memory / (2**20), 2)}Mb")
        return {
            TAG_MEMORY_USAGE: self.memory,
            TAG_CPU_TIME: self.cpu_time,
            TAG_WALL_TIME: wall_time,
            TAG_LOG_FILE: self.error_logs
        }

    @staticmethod
    def add_resources(resources_1: dict, resources_2: dict) -> dict:
        """
        Adds resources of a new stage of a component work.
        """
        memory = resources_1.get(TAG_MEMORY_USAGE, 0) + resources_2.get(TAG_MEMORY_USAGE, 0)
        cpu_time = resources_1.get(TAG_CPU_TIME, 0.0) + resources_2.get(TAG_CPU_TIME, 0.0)
        wall_time = resources_1.get(TAG_WALL_TIME, 0.0) + resources_2.get(TAG_WALL_TIME, 0.0)
        logs = resources_1.get(TAG_LOG_FILE, set()).union(resources_2.get(TAG_LOG_FILE, set()))
        return {
            TAG_MEMORY_USAGE: memory,
            TAG_CPU_TIME: cpu_time,
            TAG_WALL_TIME: wall_time,
            TAG_LOG_FILE: logs
        }
