#
# CV is a framework for continuous verification.
#
# Copyright (clade) 2018-2019 ISP RAS (http://www.ispras.ru)
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
This component build call graph and determines files and functions affected by commits.
"""

import json
import os
import sys
import traceback

from components import COMPONENT_QUALIFIER, DEFAULT_TOOL_PATH, CIF, CLADE_BASE_FILE, \
    CLADE_WORK_DIR, JSON_EXTENSION
from components.builder import Builder
from components.component import Component

DEFAULT_CALLGRAPH_FILE = "callgraph.json"
TAG_CACHE = "cached call graph"


class Qualifier(Component):
    """
    This component build call graph and determines files and functions affected by commits.
    """

    def __init__(self, builder: Builder, entrypoints_files: list):
        super().__init__(COMPONENT_QUALIFIER, builder.config)
        self.install_dir = builder.install_dir
        self.source_dir = builder.source_dir
        self.builder = builder

        os.chdir(self.source_dir)

        path_cif = self.get_tool_path(DEFAULT_TOOL_PATH[CIF])
        self.logger.debug(f"Using CIF found in directory '{path_cif}'")
        os.environ["PATH"] += os.pathsep + path_cif

        cached_result = self.component_config.get(TAG_CACHE, None)
        if cached_result and os.path.exists(cached_result):
            self.result = cached_result
            with open(self.result, "r", errors='ignore', encoding="utf8") as file_obj:
                self.content = json.load(file_obj)
        else:
            self.logger.debug("Using Clade tool to obtain function call tree")
            try:
                # noinspection PyUnresolvedReferences
                from clade import Clade
                clade = Clade(CLADE_WORK_DIR, CLADE_BASE_FILE)
                clade.parse_all()
                self.content = clade.get_callgraph()
            except Exception as exception:
                error_msg = f"Clade has failed: {exception}\n{traceback.format_exc()}"
                sys.exit(error_msg)
            self.logger.info("Clade successfully obtained call graph")

        self.logger.debug("Reading files with description of entry points")
        self.entrypoints = set()
        for file in entrypoints_files:
            if os.path.isfile(file) and file.endswith(JSON_EXTENSION):
                with open(file, errors='ignore', encoding="utf8") as data_file:
                    data = json.load(data_file)
                    identifier = os.path.basename(file)[:-len(JSON_EXTENSION)]
                    number_of_entrypoints = len(data.get("entrypoints", {}))
                    self.logger.debug(f"Description {identifier} contains "
                                      f"{number_of_entrypoints} entry points")
                    for name, _ in data.get("entrypoints", {}).items():
                        self.entrypoints.add(name)

        os.chdir(self.work_dir)

    def __find_function_calls(self, target_func, result):
        for _, values in self.content.items():
            for func, etc in values.items():
                if func == target_func:
                    for operation, args in etc.items():
                        if operation == "called_in":
                            for _, attrs in args.items():
                                for key, _ in attrs.items():
                                    if key not in result:
                                        result.add(key)
                                        self.__find_function_calls(key, result)

    def find_functions(self, target_functions):
        """
        Finds functions affected by commits.
        """
        result = set(target_functions)
        for func in target_functions:
            self.__find_function_calls(func, result)
        res = result.intersection(self.entrypoints)
        if res:
            found_funcs_str = ", ".join(res)
            self.logger.info(f"Specified commits relate with the following entry points: "
                             f"{found_funcs_str}")
        else:
            self.logger.info("Could not find any related entry points for specified commits")
            self.logger.info("Checking all subsystems, which include modifications")
        return res

    def analyse_commits(self, commits):
        """
        Finds files and functions affected by commits.
        """
        specific_functions = set()
        specific_sources = set()
        os.chdir(self.source_dir)
        for commit in commits:
            self.logger.debug(f"Checking commit '{commit}' in the source directory")
            self.builder.check_commit(commit)
            specific_sources = specific_sources.union(self.builder.get_changed_files())
            specific_functions = specific_functions.union(self.builder.get_changed_functions())
        os.chdir(self.work_dir)
        self.logger.debug(f"Modified files: '{specific_sources}'")
        self.logger.debug(f"Modified functions: '{specific_functions}'")

        return specific_sources, specific_functions

    def stop(self):
        """
        Clear cached data.
        """
        del self.content
        return self.get_component_full_stats()
