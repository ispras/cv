import json
import os
import re
import shutil
import subprocess
import sys

from component import Component
from config import COMPONENT_QUALIFIER, DEFAULT_TOOL_PATH, CIF, TAG_CLADE_CONF, CLADE_BASE_FILE, \
    CLADE_DEFAULT_CONFIG_FILE, CLADE_WORK_DIR, CLADE_CALLGRAPH, JSON_EXTENSION

DEFAULT_CALLGRAPH_FILE = "callgraph.json"
TAG_CACHE = "cached call graph"


class Qualifier(Component):
    def __init__(self, install_dir, source_dir, entrypoints_dir, config):
        super(Qualifier, self).__init__(COMPONENT_QUALIFIER, config)
        self.install_dir = install_dir
        self.source_dir = source_dir

        self.clade_conf = self.component_config.get(TAG_CLADE_CONF, None)
        if self.clade_conf:
            if not os.path.exists(self.clade_conf):
                sys.exit("Specified clade config file '{}' does not exist".format(self.clade_conf))
        else:
            self.clade_conf = os.path.join(os.getcwd(), CLADE_DEFAULT_CONFIG_FILE)

        os.chdir(self.source_dir)

        path_cif = self.get_tool_path(DEFAULT_TOOL_PATH[CIF])
        self.logger.debug("Using CIF found in directory '{}'".format(path_cif))
        os.environ["PATH"] += os.pathsep + path_cif

        cached_result = self.component_config.get(TAG_CACHE, None)
        if cached_result and os.path.exists(cached_result):
            self.result = cached_result
        else:
            self.logger.debug("Using Clade tool to obtain function call tree")
            clade_cc_cmd = "{} -w {} -c {} {}".format(CLADE_CALLGRAPH, CLADE_WORK_DIR, self.clade_conf, CLADE_BASE_FILE)
            log_file = os.path.join(self.work_dir, "qualifier.log")
            if self.runexec_wrapper(clade_cc_cmd, output_file=log_file):
                sys.exit("Clade-callgraph has failed. See details in '{}'".format(log_file))
            callgraph_file = os.path.abspath(os.path.join(CLADE_WORK_DIR, "Callgraph", DEFAULT_CALLGRAPH_FILE))
            self.result = os.path.join(self.work_dir, DEFAULT_CALLGRAPH_FILE)
            if not os.path.exists(callgraph_file):
                sys.exit("Result of clade-callgraph does not exist '{}'".format(callgraph_file))
            shutil.copy(callgraph_file, self.result)
            self.logger.info("Clade successfully obtained call graph in file '{}'".format(self.result))

        with open(self.result, "r", errors='ignore') as fh:
            self.content = json.load(fh)

        self.logger.debug("Reading files with description of entry points")
        self.entrypoints = set()
        for root, _, file_names in os.walk(entrypoints_dir):
            for file_name in file_names:
                file = os.path.join(root, file_name)
                if file.endswith(JSON_EXTENSION):
                    with open(file, errors='ignore') as data_file:
                        data = json.load(data_file)
                        identifier = os.path.relpath(file, entrypoints_dir)[:-len(JSON_EXTENSION)]
                        self.logger.debug("Description {} contains {} entry points".
                                          format(identifier, len(data.get("entrypoints", {}))))
                        for name, etc in data.get("entrypoints", {}).items():
                            self.entrypoints.add(name)

        os.chdir(self.work_dir)

    def __find_function_calls(self, target_func, result):
        for name, values in self.content.items():
            for func, etc in values.items():
                if func == target_func:
                    for op, args in etc.items():
                        if op == "called_in":
                            for source_file, attrs in args.items():
                                for key, vals in attrs.items():
                                    if key not in result:
                                        result.add(key)
                                        self.__find_function_calls(key, result)

    def find_functions(self, target_functions):
        result = set(target_functions)
        for func in target_functions:
            self.__find_function_calls(func, result)
        res = result.intersection(self.entrypoints)
        if res:
            self.logger.info("Specified commits relate with the following entry points: {}".format(", ".join(res)))
        else:
            self.logger.info("Could not find any related entry points for specified commits")
            self.logger.info("Checking all subsystems, which include modifications")
        return res

    def analyse_commits(self, commits):
        specific_functions = set()
        specific_sources = set()
        os.chdir(self.source_dir)
        for commit in commits:
            self.logger.debug("Checking commit '{}' in the source directory".format(commit))
            res = re.search(r'(\w+)\.\.(\w+)', commit)
            if res:
                start_commit = res.group(1)
                last_commit = res.group(2)
            else:
                start_commit = commit
                last_commit = commit

            # TODO: those git commands should be placed outside.
            self.command_caller("git reset --hard")
            if self.command_caller("git checkout {}".format(last_commit)):
                sys.exit("Cannot checkout to the commit '{}'".format(last_commit))

            files = subprocess.check_output("git diff --name-only {0}~1..{1}".format(start_commit, last_commit),
                                            shell=True)
            for file in files.decode("utf-8", errors="ignore").split():
                specific_sources.add(os.path.abspath(file))

            out = subprocess.check_output("git diff --function-context {0}~1..{1}".format(start_commit, last_commit),
                                          shell=True)
            prev_line = None
            for line in out.splitlines():
                line = line.decode("utf-8", errors="ignore")

                if not prev_line:
                    prev_line = line
                    continue
                else:
                    line = prev_line + line
                    prev_line = line.replace(prev_line, "")

                res = re.search(r'@@ (.+) @@(.*)(\W+)(\w+)(\s*)\((\w+)\)', line)  # Macro
                if res:
                    specific_functions.add(res.group(4))
                    specific_functions.add(res.group(6))
                res = re.search(r'@@ (.+) @@(.*)(\W+)(\w+)(\s*)\((.*)\)', line)  # Function
                if res:
                    specific_functions.add(res.group(4))
        os.chdir(self.work_dir)
        self.logger.debug("Modified files: '{}'".format(specific_sources))
        self.logger.debug("Modified functions: '{}'".format(specific_functions))

        return specific_sources, specific_functions

    def stop(self):
        del self.content
        return self.get_component_stats()
