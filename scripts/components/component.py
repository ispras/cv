import logging
import os
import re
import resource
import subprocess
import sys
import tempfile
import time

from components import TAG_DIRS, TAG_DEBUG, TAG_TOOLS, DEFAULT_TOOL_PATH, BENCHEXEC, TAG_MEMORY_USAGE, TAG_CPU_TIME, \
    TAG_WALL_TIME, TAG_LOG_FILE

DEFAULT_MEMORY_LIMIT = "3GB"
TAG_RUNEXEC = "runexec"


class Component:
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

    def __propagate_config(self):
        component_config = self.config.get(self.name, {})
        for tag in [TAG_DIRS, TAG_DEBUG, TAG_TOOLS]:
            if tag in self.config and tag not in component_config:
                component_config[tag] = self.config[tag]
        self.component_config = component_config

    def runexec_wrapper(self, cmd, output_dir=None, output_file=None):
        """
        Call a command inside RunExec tool, track its resources and redirect its output into log file.
        Note, it produces some overheads.
        :param cmd: a command to be run (as a string).
        :param output_dir: a directory, in which log files will be placed (if None, then stdout will be used).
        :param output_file: use specified path for output.
        :return: exit code of a command.
        """
        if not self.runexec:
            return self.command_caller(cmd)
        path_to_benchexec = self.get_tool_path(DEFAULT_TOOL_PATH[BENCHEXEC])
        os.environ["PATH"] += os.pathsep + path_to_benchexec

        if not output_file:
            if not output_dir:
                # redirect into console
                fd, path = tempfile.mkstemp(suffix=".log")
            else:
                fd, path = tempfile.mkstemp(dir=output_dir, suffix=".log")
            os.close(fd)
        else:
            path = output_file

        try:
            if type(cmd) is list:
                out = subprocess.check_output(["runexec", "--output", path, "--memlimit", DEFAULT_MEMORY_LIMIT, "--"]
                                              + cmd, stderr=subprocess.STDOUT)
            elif type(cmd) is str:
                out = subprocess.check_output("runexec --output {} --memlimit {} -- {}".
                                              format(path, DEFAULT_MEMORY_LIMIT, cmd), stderr=subprocess.STDOUT,
                                              shell=True)
            else:
                raise Exception("Unsupported type of command '{}'".format(cmd))
        except subprocess.CalledProcessError as e:
            cmd = str(e.cmd)
            output = e.output.decode("utf-8", errors='ignore').rstrip()
            sys.exit("RunExec has failed on command '{}' due to '{}'".format(cmd, output))
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
                with open(path, "r", errors='ignore') as fd:
                    self.logger.info("Command '{}' output".format(cmd))
                    for line in fd.readlines():
                        print(line)
                if os.path.exists(path):
                    os.remove(path)
        else:
            if exitcode and path:
                self.error_logs.add(path)

        return exitcode

    def command_caller_with_output(self, cmd: str) -> str:
        self.logger.debug("Executing command {}".format(cmd))
        try:
            return subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT).decode(errors='ignore').rstrip()
        except subprocess.CalledProcessError as e:
            self.logger.debug("Cannot execute command '{}' due to {}".format(cmd, e))
            return ""

    def command_caller(self, cmd, output_dir=None, keep_log=True):
        """
        Call a command and redirect its output into log file.
        :param cmd: a command to be run.
        :param output_dir: a directory, in which log files will be placed (if None, then stdout will be used).
        :return: exit code of a command.
        """

        if not output_dir:
            # redirect into console
            fd, path = sys.stdout, None
            if not self.debug:
                fd = subprocess.DEVNULL
        else:
            fd, path = tempfile.mkstemp(dir=output_dir, suffix=".log")
        if type(cmd) is list:
            exitcode = subprocess.call(cmd, stderr=fd, stdout=fd)
        elif type(cmd) is str:
            exitcode = subprocess.call(cmd, stderr=fd, stdout=fd, shell=True)
        else:
            raise Exception("Unsupported command '{}'".format(cmd))
        if output_dir:
            os.close(fd)
        if exitcode and path:
            if keep_log:
                self.error_logs.add(path)
            else:
                self.temp_logs.add(path)
            with open(path, "a") as fd:
                if type(cmd) is list:
                    cmd_str = " ".join(cmd)
                else:
                    cmd_str = cmd
                fd.write("\nCommand: '{}'".format(cmd_str))

        if self.debug and exitcode and path:
            with open(path, "r", errors='ignore') as fd:
                self.logger.info("Command '{}' output".format(cmd))
                for line in fd.readlines():
                    print(line)

        return exitcode

    def exec_sed_cmd(self, regexp, file, args=""):
        sed_cmd = "sed -i {} '{}' {}".format(args, regexp, file)
        if self.command_caller(sed_cmd):
            self.logger.warning("Can not execute sed command: '%s'", sed_cmd)

    def get_tool_path(self, default_path, abs_path=None):
        assert self.install_dir
        if abs_path and os.path.isabs(abs_path) and os.path.exists(abs_path):
            # Take absolute path from the config file.
            result_path = abs_path
        else:
            # Take default path.
            if isinstance(default_path, list):
                result_path = None
                for path in default_path:
                    result_path = os.path.abspath(os.path.join(self.install_dir, path))
                    if os.path.exists(result_path):
                        break
            else:
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
        self.logger.debug("Wall time: {}s".format(round(wall_time, 2)))
        self.logger.debug("CPU time: {}s".format(round(self.cpu_time, 2)))
        self.logger.debug("Memory usage: {}Mb".format(round(self.memory / (2**20))))
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
        self.logger.debug("Wall time: {}s".format(round(wall_time, 2)))
        self.logger.debug("CPU time: {}s".format(round(self.cpu_time, 2)))
        self.logger.debug("Memory usage: {}Mb".format(round(self.memory / (2**20), 2)))
        return {
            TAG_MEMORY_USAGE: self.memory,
            TAG_CPU_TIME: self.cpu_time,
            TAG_WALL_TIME: wall_time,
            TAG_LOG_FILE: self.error_logs
        }

    def add_resources(self, resources_1: dict, resources_2: dict) -> dict:
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
