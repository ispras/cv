"""
Class for representation of an arbitrary component.
"""

import json
import logging
import os
import resource
import subprocess
import sys
import tempfile
import time
from enum import Enum

from models.tags import Tag, Resource

DEFAULT_INSTALL_DIR = "tools"
TOOL_CONFIG_FILE = os.path.join(DEFAULT_INSTALL_DIR, "config.json")


class Tool(str, Enum):
    """
    Names of the external tools.
    """
    ET_HTML_LIB = "et html"
    BENCHEXEC = "benchexec"
    UPLOADER = "uploader"
    RUNEXEC = "runexec"


class Component:
    """
    Class for representation of an arbitrary component.
    """

    tools_config = {}

    @staticmethod
    def _get_tool_default_path(tool_name: str):
        #TODO: error message here?
        default_tool_path = Component.tools_config[Tag.DEFAULT_TOOL_PATH]
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
        self.runexec = self.config.get(Tool.RUNEXEC, True)
        self.__propagate_config()

        # Debug and logging.
        self.debug = self.component_config.get(Tag.DEBUG, False)
        self.logger = self._create_logger(self.name, logging.DEBUG if self.debug else logging.INFO)

        # Should be rewritten.
        self.install_dir = None
        self.error_logs = set()
        self.temp_logs = set()
        if not Component.tools_config:
            install_dir = os.path.abspath(
                os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir, os.pardir)
            )
            config_file = os.path.join(install_dir, TOOL_CONFIG_FILE)
            if os.path.exists(config_file):
                with open(config_file, encoding='ascii') as file_obj:
                    Component.tools_config = json.load(file_obj)

    def __propagate_config(self):
        """
        Propagate config for a given component (some general option can be overriden in
        component config).
        """
        component_config = self.config.get(self.name, {})
        for tag in [Tag.DIRS, Tag.DEBUG, Tag.TOOLS]:
            if tag in self.config and tag not in component_config:
                component_config[tag] = self.config[tag]
        self.component_config = component_config

    @staticmethod
    def _create_logger(logger_name: str, logger_level):
        if isinstance(logger_name, Enum):
            logger_name = str(logger_name.value)
        logger = logging.getLogger(name=logger_name)
        stream_handler = logging.StreamHandler(stream=sys.stdout)
        stream_handler.setFormatter(logging.Formatter('%(name)s: %(levelname)s: %(message)s'))
        logger.addHandler(stream_handler)
        logger.setLevel(logger_level)
        return logger

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
            Resource.MEMORY_USAGE: self.memory,
            Resource.CPU_TIME: self.cpu_time,
            Resource.WALL_TIME: wall_time,
            Tag.LOG_FILE: self.error_logs
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
            Resource.MEMORY_USAGE: self.memory,
            Resource.CPU_TIME: self.cpu_time,
            Resource.WALL_TIME: wall_time,
            Tag.LOG_FILE: self.error_logs
        }

    @staticmethod
    def add_resources(resources_1: dict, resources_2: dict) -> dict:
        """
        Adds resources of a new stage of a component work.
        """
        memory = resources_1.get(Resource.MEMORY_USAGE, 0) + resources_2.get(Resource.MEMORY_USAGE, 0)
        cpu_time = resources_1.get(Resource.CPU_TIME, 0.0) + resources_2.get(Resource.CPU_TIME, 0.0)
        wall_time = resources_1.get(Resource.WALL_TIME, 0.0) + resources_2.get(Resource.WALL_TIME, 0.0)
        logs = resources_1.get(Tag.LOG_FILE, set()).union(resources_2.get(Tag.LOG_FILE, set()))
        return {
            Resource.MEMORY_USAGE: memory,
            Resource.CPU_TIME: cpu_time,
            Resource.WALL_TIME: wall_time,
            Tag.LOG_FILE: logs
        }
