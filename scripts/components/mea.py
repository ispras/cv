import glob
import json
import logging
import multiprocessing
import operator
import re
import resource
import time
import uuid
import zipfile

# noinspection PyUnresolvedReferences
from aux.mea import DEFAULT_CONVERSION_FUNCTION, CONVERSION_FUNCTION_MODEL_FUNCTIONS, CONVERSION_FUNCTION_CALL_TREE, \
    CONVERSION_FUNCTION_NOTES, convert_error_trace, compare_error_traces, is_equivalent, DEFAULT_COMPARISON_FUNCTION, \
    DEFAULT_SIMILARITY_THRESHOLD, TAG_COMPARISON_FUNCTION, TAG_CONVERSION_FUNCTION, TAG_ADDITIONAL_MODEL_FUNCTIONS

from aux.common import *
from components import *
from components.component import Component

ERROR_TRACE_FILE = "error trace.json"
CONVERTED_ERROR_TRACES = "converted error traces.json"

TAG_PARALLEL_PROCESSES = "internal parallel processes"
TAG_CONVERSION_FUNCTION_ARGUMENTS = "conversion function arguments"
TAG_CLEAN = "clean"

EXPORTING_CONVERTED_FUNCTIONS = {
    DEFAULT_CONVERSION_FUNCTION,
    CONVERSION_FUNCTION_MODEL_FUNCTIONS,
    CONVERSION_FUNCTION_CALL_TREE,
    CONVERSION_FUNCTION_NOTES
}

DO_NOT_FILTER = "do not filter"


class MEA(Component):
    """
    Multiple Error Analysis (MEA) is aimed at processing several error traces, which violates the same property.
    Error traces are called equivalent, if they correspond to the same error.
    Error trace equivalence for two traces et1 and et2 is determined in the following way:
    et1 = et2 <=> comparison(conversion(parser(et1)), comparison(parser(et2))),
    where parser function parses the given file with error trace and returns its internal representation,
    conversion function transforms its internal representation (for example, by removing some elements) and
    comparison function compares its internal representation.
    Definitions:
    - parsed error trace - result of parser(et), et - file name with error trace (xml);
    - converted error trace - result of conversion(pet), pet - parsed error trace.
    """
    def __init__(self, general_config: dict, error_traces: list, install_dir: str, rule: str = "",
                 result_dir: str = ""):
        super(MEA, self).__init__(COMPONENT_MEA, general_config)
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
        self.parallel_processes = self.__get_option_for_rule(TAG_PARALLEL_PROCESSES, multiprocessing.cpu_count())
        self.conversion_function = self.__get_option_for_rule(TAG_CONVERSION_FUNCTION, DEFAULT_CONVERSION_FUNCTION)
        self.comparison_function = self.__get_option_for_rule(TAG_COMPARISON_FUNCTION, DEFAULT_COMPARISON_FUNCTION)
        self.conversion_function_args = self.__get_option_for_rule(TAG_CONVERSION_FUNCTION_ARGUMENTS, {})
        self.clean = self.__get_option_for_rule(TAG_CLEAN, True)

        # Cache of filtered converted error traces.
        self.__cache = dict()

        # CPU time of each operation.
        self.package_processing_time = 0.0
        self.comparison_time = 0.0

    def filter(self) -> list:
        """
        Filter error trace with specified configuration and return filtered traces.
        """
        self.logger.debug("Processing {} error traces".format(len(self.error_traces)))

        start_time = time.time()
        process_pool = list()
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
                                                                            converted_error_traces, queue))
                            process_pool[i].start()
                            raise NestedLoop
                    time.sleep(BUSY_WAITING_INTERVAL)
            except NestedLoop:
                pass
            except Exception as e:
                self.logger.error("Could not filter traces: {}".format(e), exc_info=True)
                kill_launches(process_pool)

        wait_for_launches(process_pool)
        self.__count_resource_usage(queue)
        self.package_processing_time = time.time() - start_time

        # Need to sort traces for deterministic results.
        # Moreover, first traces are usually more "simpler".
        sorted_traces = {}
        for trace in converted_error_traces.keys():
            identifier = re.search(r'witness(.*){}'.format(GRAPHML_EXTENSION), trace).group(1)
            key = identifier
            if identifier.isdigit():
                try:
                    key = int(identifier)
                except Exception as e:
                    self.logger.debug("Cannot convert to int id {} due to: {}".format(identifier, e))
            sorted_traces[key] = trace
        try:
            sorted_traces = sorted(sorted_traces.items(), key=operator.itemgetter(0))
        except Exception as e:
            sorted_traces = sorted(sorted_traces.items(), key=operator.itemgetter(1))
            self.logger.warning("Cannot sort error traces due to: {}".format(e))

        process_pool = list()
        for i in range(self.parallel_processes):
            process_pool.append(None)

        filtered_traces = []
        self.logger.debug("Filtering error traces")

        start_time = time.time()
        for identifier, error_trace_file in sorted_traces:
            converted_trace = converted_error_traces[error_trace_file]
            if not self.__compare(converted_trace, error_trace_file):
                self.logger.debug("Filtered new error trace '{}'".format(error_trace_file))
                filtered_traces.append(error_trace_file)

                try:
                    while True:
                        for i in range(self.parallel_processes):
                            if process_pool[i] and not process_pool[i].is_alive():
                                process_pool[i].join()
                                process_pool[i] = None
                            if not process_pool[i]:
                                process_pool[i] = multiprocessing.Process(target=self.__print_trace_archive,
                                                                          name=error_trace_file,
                                                                          args=(error_trace_file, ))
                                process_pool[i].start()
                                raise NestedLoop
                        time.sleep(0.1)
                except NestedLoop:
                    pass
                except Exception as e:
                    self.logger.error("Could not print filtered error traces: {}".format(e), exc_info=True)
                    kill_launches(process_pool)

        self.comparison_time = time.time() - start_time
        wait_for_launches(process_pool)

        self.memory += int(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss) * 1024

        self.logger.info("Filtering has been completed: {0} -> {1}".format(len(self.error_traces),
                                                                           len(filtered_traces)))
        self.logger.debug("Package processing of error traces took {}s".format(round(self.package_processing_time, 2)))
        self.logger.debug("Comparing error traces took {}s".format(round(self.comparison_time, 2)))
        self.clear()
        self.get_component_stats()
        return filtered_traces

    def process_traces_without_filtering(self) -> bool:
        """
        Process all traces (parse, create cache of converted functions, print results to archive) without filtering.
        """
        is_exported = False
        for error_trace_file in self.error_traces:
            converted_error_traces = dict()
            if self.__process_trace(error_trace_file, converted_error_traces):
                self.__print_trace_archive(error_trace_file)
                is_exported = True
        self.memory = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
        return is_exported

    def __process_trace(self, error_trace_file: str, converted_error_traces: dict, queue: multiprocessing.Queue = None):
        parsed_error_trace = self.__parse_trace(error_trace_file)
        if parsed_error_trace:
            self.__process_parsed_trace(parsed_error_trace)
            if self.clean:
                os.remove(error_trace_file)
            self.logger.debug("Trace '{0}' has been parsed".format(error_trace_file))

            converted_error_trace = convert_error_trace(parsed_error_trace, self.conversion_function,
                                                        self.conversion_function_args)
            self.__print_parsed_error_trace(parsed_error_trace, converted_error_trace, error_trace_file)
            converted_error_traces[error_trace_file] = converted_error_trace

        if queue:
            user_time, system_time, memory = resource.getrusage(resource.RUSAGE_SELF)[0:3]
            queue.put({
                TAG_CPU_TIME: float(user_time + system_time),
                TAG_MEMORY_USAGE: int(memory) * 1024
            })
            sys.exit(0)
        else:
            return bool(parsed_error_trace)

    def __compare(self, converted_trace: list, file_name: str) -> bool:
        """
        Compare converted error traces.
        """
        if self.comparison_function == DO_NOT_FILTER:
            return False
        equivalent_trace = None
        for filtered_file_name, filtered_converted_trace in self.__cache.items():
            compare_result = compare_error_traces(converted_trace, filtered_converted_trace, self.comparison_function)
            if is_equivalent(compare_result, DEFAULT_SIMILARITY_THRESHOLD):
                equivalent_trace = filtered_file_name
                break

        if equivalent_trace:
            self.logger.debug("Error trace '{}' is equivalent to already filtered error trace '{}'".
                              format(file_name, equivalent_trace))
            equivalent = True
        else:
            self.__cache[file_name] = converted_trace
            equivalent = False
        return equivalent

    def __print_trace_archive(self, error_trace_file_name: str):
        json_trace_name, source_files, converted_traces_files = self.__get_aux_file_names(error_trace_file_name)
        archive_name = error_trace_file_name[:-len(GRAPHML_EXTENSION)] + ARCHIVE_EXTENSION
        with zipfile.ZipFile(archive_name, mode='w', compression=zipfile.ZIP_DEFLATED) as zfp:
            zfp.write(json_trace_name, arcname=ERROR_TRACE_FILE)
            zfp.write(source_files, arcname=ERROR_TRACE_SOURCES)
            zfp.write(converted_traces_files, arcname=CONVERTED_ERROR_TRACES)
        if self.result_dir:
            os.environ.setdefault("DJANGO_SETTINGS_MODULE", "bridge.settings")
            import django
            django.setup()
            # noinspection PyUnresolvedReferences
            from reports.etv import convert_json_trace_to_html
            with open(json_trace_name) as fd:
                content = fd.read()
            name = os.path.join(self.result_dir, "{}_{}".format(uuid.uuid4().hex, os.path.basename(archive_name)))
            self.logger.info("Exporting html error trace '{}'".format(name))
            convert_json_trace_to_html(content, name)
        os.remove(json_trace_name)
        os.remove(source_files)
        os.remove(converted_traces_files)

    @staticmethod
    def __process_parsed_trace(parsed_error_trace: dict):
        # Normalize source paths.
        src_files = list()
        for src_file in parsed_error_trace['files']:
            src_file = os.path.normpath(src_file)
            src_files.append(src_file)
        parsed_error_trace['files'] = src_files

    def __parse_trace(self, error_trace_file: str) -> dict:
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
            return import_error_trace(logger, error_trace_file)
        except Exception as e:
            self.logger.warning("Trace '{}' can not by parsed due to: {}".format(error_trace_file, e), exc_info=True)
            return {}

    def __print_parsed_error_trace(self, parsed_error_trace: dict, converted_error_trace: list, error_trace_file: str):
        json_trace_name, source_files, converted_traces_files = self.__get_aux_file_names(error_trace_file)

        with open(json_trace_name, 'w', encoding='utf8') as fp:
            json.dump(parsed_error_trace, fp, ensure_ascii=False, sort_keys=True, indent="\t")

        with open(source_files, 'w', encoding='utf8') as fp:
            json.dump(parsed_error_trace['files'], fp, ensure_ascii=False, sort_keys=True, indent="\t")

        converted_traces = dict()
        for conversion_function in EXPORTING_CONVERTED_FUNCTIONS:
            if conversion_function == self.conversion_function and not self.conversion_function_args:
                converted_traces[conversion_function] = converted_error_trace
            else:
                # Important note: here we create converted error trace without params.
                converted_traces[conversion_function] = \
                    convert_error_trace(parsed_error_trace, conversion_function, {})
        with open(converted_traces_files, 'w', encoding='utf8') as fp:
            json.dump(converted_traces, fp, ensure_ascii=False, sort_keys=True, indent="\t")

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
        et_parser_lib = self.get_tool_path(DEFAULT_TOOL_PATH[ET_LIB], self.config.get(TAG_TOOLS, {}).get(ET_LIB))
        sys.path.append(et_parser_lib)
        et_html_lib = self.get_tool_path(DEFAULT_TOOL_PATH[ET_HTML_LIB], self.config.get(TAG_TOOLS, {}).
                                         get(ET_HTML_LIB))
        sys.path.append(et_html_lib)

    def clear(self):
        if self.error_traces:
            work_dir = os.path.dirname(self.error_traces[0])
            for file in glob.glob(os.path.join(work_dir, "*{}".format(JSON_EXTENSION))):
                os.remove(file)
