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
# pylint: disable=no-name-in-module

"""
This module implements Multiple Error Analysis (MEA).
"""

import glob
import json
import logging
import multiprocessing
import operator
import re
import resource
import time
import zipfile

# noinspection PyUnresolvedReferences
from aux.mea import DEFAULT_CONVERSION_FUNCTION, CONVERSION_FUNCTION_MODEL_FUNCTIONS, \
    CONVERSION_FUNCTION_CALL_TREE, CONVERSION_FUNCTION_NOTES, convert_error_trace, \
    compare_error_traces, is_equivalent, DEFAULT_COMPARISON_FUNCTION, \
    DEFAULT_SIMILARITY_THRESHOLD, TAG_COMPARISON_FUNCTION, TAG_CONVERSION_FUNCTION, \
    TAG_ADDITIONAL_MODEL_FUNCTIONS, CONVERSION_FUNCTION_FULL

from aux.common import *
from components import *
from components.component import Component

ERROR_TRACE_FILE = "error trace.json"
CONVERTED_ERROR_TRACES = "converted error traces.json"

TAG_PARALLEL_PROCESSES = "internal parallel processes"
TAG_CONVERSION_FUNCTION_ARGUMENTS = "conversion function arguments"
TAG_CLEAN = "clean"
TAG_UNZIP = "unzip"
TAG_DRY_RUN = "dry run"
TAG_SOURCE_DIR = "source dir"

EXPORTING_CONVERTED_FUNCTIONS = {
    DEFAULT_CONVERSION_FUNCTION,
    CONVERSION_FUNCTION_MODEL_FUNCTIONS,
    CONVERSION_FUNCTION_CALL_TREE,
    CONVERSION_FUNCTION_NOTES
}

DO_NOT_FILTER = "do not filter"


class MEA(Component):
    """
    Multiple Error Analysis (MEA) is aimed at processing several error traces, which violates 
    the same property. Error traces are called equivalent, if they correspond to the same error.
    Error trace equivalence for two traces et1 and et2 is determined in the following way:
    et1 = et2 <=> comparison(conversion(parser(et1)), comparison(parser(et2))),
    where parser function parses the given file with error trace and returns its internal 
    representation, conversion function transforms its internal representation (for example, 
    by removing some elements) and comparison function compares its internal representation.
    Definitions:
    - parsed error trace - result of parser(et), et - file name with error trace (xml);
    - converted error trace - result of conversion(pet), pet - parsed error trace.
    """
    def __init__(self, general_config: dict, error_traces: list, install_dir: str, rule: str = "",
                 result_dir: str = "", is_standalone=False):
        super().__init__(COMPONENT_MEA, general_config)
        self.install_dir = install_dir
        if result_dir:
            self.result_dir = os.path.join(result_dir, rule)
            if not os.path.exists(self.result_dir):
                os.makedirs(self.result_dir, exist_ok=True)
        else:
            self.result_dir = None
        self.__export_et_parser_lib()
        self.rule = rule

        # List of files with error traces.
        self.error_traces = error_traces

        # Config options.
        self.parallel_processes = self.__get_option_for_rule(TAG_PARALLEL_PROCESSES,
                                                             multiprocessing.cpu_count())
        self.conversion_function = self.__get_option_for_rule(TAG_CONVERSION_FUNCTION,
                                                              DEFAULT_CONVERSION_FUNCTION)
        self.comparison_function = self.__get_option_for_rule(TAG_COMPARISON_FUNCTION,
                                                              DEFAULT_COMPARISON_FUNCTION)
        self.conversion_function_args = self.__get_option_for_rule(
            TAG_CONVERSION_FUNCTION_ARGUMENTS, {})
        self.clean = self.__get_option_for_rule(TAG_CLEAN, True)
        self.unzip = self.__get_option_for_rule(TAG_UNZIP, True)
        self.dry_run = self.__get_option_for_rule(TAG_DRY_RUN, False)
        self.source_dir = self.__get_option_for_rule(TAG_SOURCE_DIR, None)

        # Cache of filtered converted error traces.
        self.__cache = {}

        # CPU time of each operation.
        self.package_processing_time = 0.0
        self.comparison_time = 0.0
        self.is_standalone = is_standalone

    def filter(self) -> list:
        """
        Filter error trace with specified configuration and return filtered traces.
        """
        self.logger.debug(f"Processing {len(self.error_traces)} error traces")

        start_time = time.time()
        process_pool = []
        queue = multiprocessing.Queue()
        converted_error_traces = multiprocessing.Manager().dict()
        for i in range(self.parallel_processes):
            process_pool.append(None)
        for error_trace_file in self.error_traces:
            try:
                while True:
                    for i in range(self.parallel_processes):
                        if process_pool[i] and not process_pool[i].is_alive():
                            process_pool[i].join()
                            process_pool[i] = None
                        if not process_pool[i]:
                            process_pool[i] = multiprocessing.Process(target=self.__process_trace,
                                                                      name=error_trace_file,
                                                                      args=(error_trace_file,
                                                                            converted_error_traces,
                                                                            queue))
                            process_pool[i].start()
                            raise NestedLoop
                    time.sleep(BUSY_WAITING_INTERVAL)
            except NestedLoop:
                pass
            except Exception as exception:
                self.logger.error(f"Could not filter traces: {exception}", exc_info=True)
                kill_launches(process_pool)

        wait_for_launches(process_pool)
        self.__count_resource_usage(queue)
        self.package_processing_time = time.time() - start_time

        # Need to sort traces for deterministic results.
        # Moreover, first traces are usually more "simpler".
        sorted_traces = {}
        for trace in converted_error_traces.keys():
            identifier = re.search(rf'witness(.*){GRAPHML_EXTENSION}', trace).group(1)
            key = identifier
            if identifier.isdigit():
                try:
                    key = int(identifier)
                except Exception as exception:
                    self.logger.debug(f"Cannot convert to int id {identifier} due to: {exception}")
            sorted_traces[key] = trace
        try:
            sorted_traces = sorted(sorted_traces.items(), key=operator.itemgetter(0))
        except Exception as exception:
            sorted_traces = sorted(sorted_traces.items(), key=operator.itemgetter(1))
            self.logger.warning(f"Cannot sort error traces due to: {exception}")

        process_pool = []
        for i in range(self.parallel_processes):
            process_pool.append(None)

        filtered_traces = []
        self.logger.debug("Filtering error traces")

        start_time = time.time()
        for identifier, error_trace_file in sorted_traces:
            converted_trace = converted_error_traces[error_trace_file]
            if not self.__compare(converted_trace, error_trace_file):
                self.logger.debug(f"Filtered new error trace '{error_trace_file}'")
                filtered_traces.append(error_trace_file)

                try:
                    while True:
                        for i in range(self.parallel_processes):
                            if process_pool[i] and not process_pool[i].is_alive():
                                process_pool[i].join()
                                process_pool[i] = None
                            if not process_pool[i]:
                                process_pool[i] = multiprocessing.Process(
                                    target=self.__print_trace_archive, name=error_trace_file,
                                    args=(error_trace_file, ))
                                process_pool[i].start()
                                raise NestedLoop
                        time.sleep(0.1)
                except NestedLoop:
                    pass
                except Exception as exception:
                    self.logger.error(f"Could not print filtered error traces: {exception}",
                                      exc_info=True)
                    kill_launches(process_pool)

        self.comparison_time = time.time() - start_time
        wait_for_launches(process_pool)

        self.memory += int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss) * 1024

        if not self.comparison_function == DO_NOT_FILTER:
            self.logger.info(f"Filtering has been completed: "
                             f"{len(self.error_traces)} -> {len(filtered_traces)}")
        self.logger.debug(f"Package processing of error traces took "
                          f"{round(self.package_processing_time, 2)}s")
        self.logger.debug(f"Comparing error traces took {round(self.comparison_time, 2)}s")
        self.clear()
        self.get_component_stats()
        return filtered_traces

    def process_traces_without_filtering(self) -> tuple:
        """
        Process all traces (parse, create cache of converted functions, print results to archive)
        without filtering.
        """
        is_exported = False
        witness_type = WITNESS_VIOLATION
        for error_trace_file in self.error_traces:
            converted_error_traces = {}
            is_exported, witness_type = self.__process_trace(error_trace_file,
                                                             converted_error_traces)
            if is_exported:
                self.__print_trace_archive(error_trace_file, witness_type)
        self.memory = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
        return is_exported, witness_type

    def __process_trace(self, error_trace_file: str, converted_error_traces: dict,
                        queue: multiprocessing.Queue = None):
        # TODO: if we receive several witnesses they are considered to be violation witnesses only.
        if queue and not self.is_standalone:
            supported_types = {WITNESS_VIOLATION}
        else:
            supported_types = {WITNESS_VIOLATION, WITNESS_CORRECTNESS}
        parsed_error_trace = self.__parse_trace(error_trace_file, supported_types)
        if parsed_error_trace:
            self.__process_parsed_trace(parsed_error_trace)
            if self.clean:
                os.remove(error_trace_file)
            self.logger.debug(f"Trace '{error_trace_file}' has been parsed")

            if parsed_error_trace.get('type') == WITNESS_CORRECTNESS:
                conversion_function = CONVERSION_FUNCTION_FULL
            else:
                conversion_function = self.conversion_function
            converted_error_trace = convert_error_trace(parsed_error_trace, conversion_function,
                                                        self.conversion_function_args)
            self.__print_parsed_error_trace(parsed_error_trace, converted_error_trace,
                                            error_trace_file)
            converted_error_traces[error_trace_file] = converted_error_trace

        if queue:
            user_time, system_time, memory = resource.getrusage(resource.RUSAGE_SELF)[0:3]
            queue.put({
                TAG_CPU_TIME: float(user_time + system_time),
                TAG_MEMORY_USAGE: int(memory) * 1024
            })
            sys.exit(0)
        else:
            return bool(parsed_error_trace), parsed_error_trace.get('type', WITNESS_VIOLATION)

    def __compare(self, converted_trace: list, file_name: str) -> bool:
        """
        Compare converted error traces.
        """
        if self.comparison_function == DO_NOT_FILTER:
            return False
        equivalent_trace = None
        for filtered_file_name, filtered_converted_trace in self.__cache.items():
            compare_result = compare_error_traces(converted_trace, filtered_converted_trace,
                                                  self.comparison_function)
            if is_equivalent(compare_result, DEFAULT_SIMILARITY_THRESHOLD):
                equivalent_trace = filtered_file_name
                break

        if equivalent_trace:
            self.logger.debug(f"Error trace '{file_name}' is equivalent to already filtered "
                              f"error trace '{equivalent_trace}'")
            equivalent = True
        else:
            self.__cache[file_name] = converted_trace
            equivalent = False
        return equivalent

    def __print_trace_archive(self, error_trace_file_name: str, witness_type=WITNESS_VIOLATION):
        json_trace_name, source_files, converted_traces_files = \
            self.__get_aux_file_names(error_trace_file_name)
        archive_name = error_trace_file_name[:-len(GRAPHML_EXTENSION)] + ARCHIVE_EXTENSION
        archive_name_base = os.path.basename(archive_name)
        if self.is_standalone:
            mandatory_prefix = "witness"
        else:
            mandatory_prefix = f"{witness_type}_witness"
        if not archive_name_base.startswith(mandatory_prefix):
            archive_name_base = f"{mandatory_prefix}.{archive_name_base}"
            archive_name = os.path.join(os.path.dirname(archive_name), archive_name_base)
        with zipfile.ZipFile(archive_name, mode='w', compression=zipfile.ZIP_DEFLATED) as zfp:
            zfp.write(json_trace_name, arcname=ERROR_TRACE_FILE)
            zfp.write(source_files, arcname=ERROR_TRACE_SOURCES)
            zfp.write(converted_traces_files, arcname=CONVERTED_ERROR_TRACES)
        if self.result_dir:
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bridge.settings")
            import django
            from django.conf import settings
            settings.INSTALLED_APPS = (
                'django.contrib.admin',
                'django.contrib.auth',
                'django.contrib.contenttypes',
                'django.contrib.humanize',
                'django.contrib.sessions',
                'django.contrib.messages',
                'django.contrib.staticfiles',
                'reports',
            )
            django.setup()
            # noinspection PyUnresolvedReferences
            from reports.etv import convert_json_trace_to_html
            with open(json_trace_name, encoding="utf8") as trace_file:
                content = trace_file.read()
            name = os.path.join(self.result_dir, os.path.basename(archive_name))
            self.logger.info(f"Exporting html error trace '{name}'")
            convert_json_trace_to_html(content, name)
            if self.unzip:
                self.command_caller(f'unzip -d "{self.result_dir}" -o "{name}"')
        os.remove(json_trace_name)
        os.remove(source_files)
        os.remove(converted_traces_files)
        if self.is_standalone and not self.debug:
            os.remove(archive_name)

    @staticmethod
    def __process_parsed_trace(parsed_error_trace: dict):
        # Normalize source paths.
        src_files = []
        for src_file in parsed_error_trace['files']:
            src_file = os.path.normpath(src_file)
            src_files.append(src_file)
        parsed_error_trace['files'] = src_files

    def __parse_trace(self, error_trace_file: str, supported_types: set) -> dict:
        # noinspection PyUnresolvedReferences
        from core.vrp.et import import_error_trace

        # Those messages are waste of space.
        logger = logging.getLogger(name="Witness processor")
        logging.basicConfig(format='%(name)s: %(levelname)s: %(message)s')
        if self.debug:
            logger.setLevel(logging.WARNING)
        else:
            logger.setLevel(logging.ERROR)
        try:
            json_error_trace = import_error_trace(logger, error_trace_file, self.source_dir)
            if self.dry_run:
                warnings = json_error_trace.get('warnings', [])
                if warnings:
                    self.logger.warning(
                        f"There are missing elements for witness {error_trace_file}:")
                    for warning in warnings:
                        print(warning)
                else:
                    self.logger.info(
                        f"There are no missing elements for witness {error_trace_file}")
                return {}
            witness_type = json_error_trace.get('type')
            if witness_type not in supported_types:
                self.logger.warning(f'Witness type {witness_type} is not supported')
                return {}
            return json_error_trace
        except Exception as exception:
            self.logger.warning(f"Trace '{error_trace_file}' can not by parsed due to: {exception}")
            self.logger.debug("Exception stack: ", exc_info=True)
            return {}

    def __print_parsed_error_trace(self, parsed_error_trace: dict, converted_error_trace: list,
                                   error_trace_file: str):
        json_trace_name, source_files, converted_traces_files = \
            self.__get_aux_file_names(error_trace_file)

        with open(json_trace_name, 'w', encoding='utf8') as file_obj:
            json.dump(parsed_error_trace, file_obj, ensure_ascii=False, sort_keys=True, indent="\t")

        with open(source_files, 'w', encoding='utf8') as file_obj:
            json.dump(parsed_error_trace['files'], file_obj, ensure_ascii=False, sort_keys=True,
                      indent="\t")

        converted_traces = {}
        if parsed_error_trace.get('type') == WITNESS_VIOLATION:
            for conversion_function in EXPORTING_CONVERTED_FUNCTIONS:
                if conversion_function == self.conversion_function and \
                        not self.conversion_function_args:
                    converted_traces[conversion_function] = converted_error_trace
                else:
                    # Important note: here we create converted error trace without params.
                    converted_traces[conversion_function] = \
                        convert_error_trace(parsed_error_trace, conversion_function, {})
        with open(converted_traces_files, 'w', encoding='utf8') as file_obj:
            json.dump(converted_traces, file_obj, ensure_ascii=False, sort_keys=True, indent="\t")

    @staticmethod
    def __get_aux_file_names(error_trace_file: str) -> tuple:
        # Returns the following files: json_trace, source_files, converted_traces
        common_part = error_trace_file[:-len(GRAPHML_EXTENSION)] + "_"
        json_trace_name = common_part + JSON_EXTENSION
        source_files = common_part + ERROR_TRACE_SOURCES
        converted_traces_files = common_part + CONVERTED_ERROR_TRACES
        return json_trace_name, source_files, converted_traces_files

    def __count_resource_usage(self, queue: multiprocessing.Queue):
        memory_usage_all = []
        children_memory = 0
        while not queue.empty():
            resources = queue.get()
            memory_usage_all.append(resources.get(TAG_MEMORY_USAGE, 0))
            self.cpu_time += resources.get(TAG_CPU_TIME, 0.0)
        for memory_usage in sorted(memory_usage_all)[:self.parallel_processes]:
            children_memory += memory_usage
        process_memory = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
        self.memory = max(process_memory + children_memory, self.memory)

    def __get_option_for_rule(self, tag: str, default_value):
        default = self.component_config.get(tag, default_value)
        return self.component_config.get(self.rule, {}).get(tag, default)

    def __export_et_parser_lib(self):
        et_parser_lib = self.get_tool_path(DEFAULT_TOOL_PATH[ET_LIB],
                                           self.config.get(TAG_TOOLS, {}).get(ET_LIB))
        sys.path.append(et_parser_lib)
        et_html_lib = self.get_tool_path(DEFAULT_TOOL_PATH[ET_HTML_LIB],
                                         self.config.get(TAG_TOOLS, {}).get(ET_HTML_LIB))
        sys.path.append(et_html_lib)

    def clear(self):
        """
        Clear all aux files.
        """
        if self.error_traces:
            work_dir = os.path.dirname(self.error_traces[0])
            for file in glob.glob(os.path.join(work_dir, f"*{JSON_EXTENSION}")):
                os.remove(file)
