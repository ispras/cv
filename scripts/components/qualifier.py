import json
import os
import sys
import traceback

from components import COMPONENT_QUALIFIER, DEFAULT_TOOL_PATH, CIF, CLADE_BASE_FILE, CLADE_WORK_DIR, JSON_EXTENSION
from components.builder import Builder
from components.component import Component

DEFAULT_CALLGRAPH_FILE = "callgraph.json"
TAG_CACHE = "cached call graph"


class Qualifier(Component):
    def __init__(self, builder: Builder, entrypoints_files: list):
        super(Qualifier, self).__init__(COMPONENT_QUALIFIER, builder.config)
        self.install_dir = builder.install_dir
        self.source_dir = builder.source_dir
        self.builder = builder

        os.chdir(self.source_dir)

        path_cif = self.get_tool_path(DEFAULT_TOOL_PATH[CIF])
        self.logger.debug("Using CIF found in directory '{}'".format(path_cif))
        os.environ["PATH"] += os.pathsep + path_cif

        cached_result = self.component_config.get(TAG_CACHE, None)
        if cached_result and os.path.exists(cached_result):
            self.result = cached_result
            with open(self.result, "r", errors='ignore') as fh:
                self.content = json.load(fh)
        else:
            self.logger.debug("Using Clade tool to obtain function call tree")
            try:
                # noinspection PyUnresolvedReferences
                from clade import Clade
                c = Clade(CLADE_WORK_DIR, CLADE_BASE_FILE)
                c.parse_all()
                self.content = c.get_callgraph()
            except Exception:
                error_msg = "Clade has failed: {}".format(traceback.format_exc())
                sys.exit(error_msg)
            self.logger.info("Clade successfully obtained call graph")

        self.logger.debug("Reading files with description of entry points")
        self.entrypoints = set()
        for file in entrypoints_files:
            if os.path.isfile(file) and file.endswith(JSON_EXTENSION):
                with open(file, errors='ignore') as data_file:
                    data = json.load(data_file)
                    identifier = os.path.basename(file)[:-len(JSON_EXTENSION)]
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
            self.builder.check_commit(commit)
            specific_sources = specific_sources.union(self.builder.get_changed_files())
            specific_functions = specific_functions.union(self.builder.get_changed_functions())
        os.chdir(self.work_dir)
        self.logger.debug("Modified files: '{}'".format(specific_sources))
        self.logger.debug("Modified functions: '{}'".format(specific_functions))

        return specific_sources, specific_functions

    def stop(self):
        del self.content
        return self.get_component_full_stats()
