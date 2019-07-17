#!/usr/bin/python3

import argparse
import datetime
import glob
import json
import multiprocessing
import re
import resource
import shutil
import subprocess
import tempfile
import time
from collections import deque
from time import sleep
from xml.dom import minidom
from xml.etree import ElementTree

from builder import Builder
from common import *
from component import Component
from config import *
from coverage import Coverage
from export_results import Exporter
from generate_main import MainGenerator
from mea import MEA
from preparation import Preparator
from qualifier import Qualifier

DEFAULT_CIL_DIR = "cil"
DEFAULT_MAIN_DIR = "main"
DEFAULT_LAUNCHES_DIR = "launches"
DEFAULT_SOURCE_PATCHES_DIR = "patches/sources"
DEFAULT_PREPARATION_PATCHES_DIR = "patches/preparation"
DEFAULT_ENTRYPOINTS_DIR = "entrypoints"
DEFAULT_RULES_DIR = "rules"
DEFAULT_PLUGIN_DIR = "plugin"

DEFAULT_BACKUP_PREFIX = "backup_"

TAG_LIMIT_MEMORY = "memory size"
TAG_LIMIT_CPU_TIME = "CPU time"
TAG_LIMIT_CPU_CORES = "number of cores"
TAG_OPTIMIZE = "optimize"
TAG_CACHED = "cached"
TAG_BRANCH = "branch"
TAG_PATCH = "patches"
TAG_BUILD_PATCH = "build patch"
TAG_FIND_COVERAGE = "find coverage"
TAG_CALLERS = "callers"
TAG_COMMITS = "commits"
TAG_BACKUP_WRITE = "backup write"
TAG_BACKUP_READ = "backup read"
TAG_BENCHMARK_ARGS = "benchmark args"
TAG_PARALLEL_LAUNCHES = "parallel launches"
TAG_RESOURCE_LIMITATIONS = "resource limits"
TAG_PROCESSES = "processes"
TAG_SCHEDULER = "scheduler"
TAG_CLOUD = "cloud"
TAG_CLOUD_MASTER = "master"
TAG_CLOUD_PRIORITY = "priority"
TAG_UPLOADER_UPLOAD_RESULTS = "upload results"
TAG_UPLOADER_IDENTIFIER = "identifier"
TAG_UPLOADER_SERVER = "server"
TAG_UPLOADER_USER = "user"
TAG_UPLOADER_PASSWORD = "password"
TAG_UPLOADER_PARENT_ID = "parent id"
TAG_SKIP = "skip"
TAG_STATISTICS_TIME = "statistics time"
TAG_BUILD_CONFIG = "build config"
TAG_ID = "id"
TAG_REPOSITORY = "repository"
TAG_NAME = "name"
TAG_VERIFIER_OPTIONS = "verifier options"
TAG_EXPORT_HTML_ERROR_TRACES = "standalone error traces"

TIMESTAMP_PATTERN = "<timestamp>"
COMMIT_PATTERN = "<commit>"

SCHEDULER_CLOUD = "cloud"
SCHEDULER_LOCAL = "local"
SCHEDULERS = [SCHEDULER_CLOUD, SCHEDULER_LOCAL]

CLOUD_PRIORITIES = ["IDLE", "LOW", "HIGH", "URGENT"]
DEFAULT_CLOUD_PRIORITY = "LOW"
CLOUD_BENCHMARK_LOG = "benchmark_log.txt"

HARDCODED_RACES_OUTPUT_DIR = "output"

ROUND_DIGITS = 9  # nanoseconds.

DEFAULT_TIME_FOR_STATISTICS = 0  # By default we do not allocate time for printing statistics.

VERIFIER_OPTIONS_NOT_OPTIMIZED = [
    "cpa.functionpointer.ignoreUnknownFunctionPointerCalls=false",
]

VERIFIER_FILES_DIR = "verifier_files"
VERIFIER_OPTIONS_DIR = "options"
VERIFIER_PROPERTIES_DIR = "properties"

VERIFIER_OPTIONS_COMMON = "common"

SOURCE_QUEUE_BUILDER_RESOURCES = "builder resources"
SOURCE_QUEUE_QUALIFIER_RESOURCES = "qualifier resources"
SOURCE_QUEUE_FILES = "files"
SOURCE_QUEUE_FUNCTIONS = "functions"
SOURCE_QUEUE_RESULTS = "results"

TAG_ENTRYPOINTS_DESC = "entrypoints desc"
TAG_PREPARATION_CONFIG = "preparation config"
DEFAULT_PREPARATION_CONFIG = "conf.json"
DEFAULT_PROPERTY_MEMSAFETY = "properties/memsafety.spc"
DEFAULT_PROPERTY_UNREACHABILITY = "properties/unreachability.spc"


class EntryPointDesc:
    def __init__(self, file: str, identifier: str):
        self.file = file
        with open(file, errors='ignore') as fd:
            data = json.load(fd)
            metadata = data.get(TAG_METADATA, {})
            self.optimize = metadata.get(TAG_OPTIMIZE, False)
            self.subsystem = metadata.get(TAG_SUBSYSTEM, ".")
        self.id = identifier  # Path in the entrypoints directory (may contain subdirectories).
        self.short_name = re.sub("\W", "_", identifier)  # Should be used in path concatenations.

    def __str__(self):
        return self.id


# TODO: move it to some results processor class (Component) to operate with arbitrary BenchExec output directory.
class VerificationTask:
    def __init__(self, entry_desc: EntryPointDesc, rule, entrypoint, path_to_verifier, cil_file):
        self.entry_desc = entry_desc
        self.rule = rule
        self.entrypoint = entrypoint
        if self.rule == RULE_COVERAGE:
            self.mode = COVERAGE
        elif self.rule == RULE_MEMSAFETY:
            self.mode = MEMSAFETY
        elif self.rule == RULE_RACES:
            self.mode = RACES
        elif self.rule in DEADLOCK_SUB_PROPERTIES:
            self.mode = DEADLOCK
        else:
            self.mode = UNREACHABILITY
        self.path_to_verifier = path_to_verifier
        self.cil_file = cil_file
        self.name = "_".join([self.entry_desc.id, self.rule, self.entrypoint])

    def copy(self):
        return type(self)(self.entry_desc, self.rule, self.entrypoint, self.path_to_verifier, self.cil_file)


class VerificationResults:
    def __init__(self, verification_task, config: dict):
        if verification_task:
            self.id = verification_task.entry_desc.subsystem
            self.rule = verification_task.rule
            self.entrypoint = verification_task.entrypoint
        else:
            self.id = None
            self.rule = None
            self.entrypoint = None
        self.cpu = 0
        self.filtering_cpu = 0
        self.filtering_mem = 0
        self.mem = 0
        self.wall = 0
        self.verdict = VERDICT_UNKNOWN
        self.termination_reason = ""
        self.relevant = False
        self.initial_traces = 0
        self.work_dir = None
        self.cov_lines = 0.0
        self.cov_funcs = 0.0
        self.filtered_traces = 0
        self.debug = config.get(TAG_DEBUG, False)
        self.config = config
        self.coverage_resources = dict()

    def is_equal(self, verification_task: VerificationTask):
        return self.id == verification_task.entry_desc.subsystem and \
               self.rule == verification_task.rule and \
               self.entrypoint == verification_task.entrypoint

    def parse_output_dir(self, launch_dir: str, install_dir: str, result_dir: str):
        # Process BenchExec log file.
        for file in glob.glob(os.path.join(launch_dir, 'benchmark*.xml')):
            tree = ElementTree.ElementTree()
            tree.parse(file)
            root = tree.getroot()
            for column in root.findall('./run/column'):
                title = column.attrib['title']
                if title == 'status':
                    self.verdict = column.attrib['value']
                    if 'true' in self.verdict:
                        self.verdict = VERDICT_SAFE
                        self.termination_reason = TERMINATION_SUCCESS
                    elif 'false' in self.verdict:
                        self.verdict = VERDICT_UNSAFE
                        self.termination_reason = TERMINATION_SUCCESS
                    else:
                        self.termination_reason = self.verdict
                        self.verdict = VERDICT_UNKNOWN
                elif title == 'cputime':
                    value = column.attrib['value']
                    self.cpu = int(float(value[:-1]))
                elif title == 'walltime':
                    value = column.attrib['value']
                    self.wall = int(float(value[:-1]))
                elif title == 'memUsage':
                    value = column.attrib['value']
                    self.mem = int(int(value) / 1000000)

        # Process log file
        try:
            usual_log_files = glob.glob(os.path.join(launch_dir, 'benchmark*logfiles/*.log'))
            if usual_log_files:
                log_file = usual_log_files[0]
            else:
                log_file = glob.glob(os.path.join(launch_dir, 'log.txt'))[0]
            with open(log_file, errors='ignore') as f_res:
                for line in f_res.readlines():
                    res = re.search(r'Number of refinements:(\s+)(\d+)', line)
                    if res:
                        if int(res.group(2)) > 1:
                            self.relevant = True
                    if self.rule == TERMINATION:
                        if re.search(r'The program will never terminate\.', line):
                            self.verdict = VERDICT_UNSAFE
            shutil.move(log_file, "{0}/log.txt".format(launch_dir))
        except IndexError:
            print("WARNING: log file was not found for entry point '{}'".format(self.entrypoint))
            pass

        error_traces = glob.glob("{}/witness*".format(launch_dir))
        self.initial_traces = len(error_traces)
        self.filtered_traces = self.initial_traces

        if not self.verdict == VERDICT_SAFE:
            self.relevant = True

        # If there is only one trace, filtering will not be performed and it will not be examined.
        if self.initial_traces == 1:
            # Trace should be checked if it is correct or not.
            mea = MEA(self.config, error_traces, install_dir, self.rule, result_dir)
            if mea.process_traces_without_filtering():
                # Trace is fine, just recheck final verdict.
                self.verdict = VERDICT_UNSAFE
            else:
                # Trace is bad, most likely verifier was killed during its printing, so just delete it.
                self.verdict = VERDICT_UNKNOWN
                self.initial_traces = 0
                self.filtered_traces = 0

        # Remove auxiliary files.
        if not self.debug:
            for file in glob.glob(os.path.join(launch_dir, "benchmark*")):
                if os.path.isdir(file):
                    shutil.rmtree(file, ignore_errors=True)
                else:
                    os.remove(file)

    def filter_traces(self, launch_dir: str, install_dir: str, result_dir: str):
        # Perform Multiple Error Analysis to filter found error traces (only for several traces).
        start_time_cpu = time.process_time()
        traces = glob.glob("{}/witness*".format(launch_dir))
        mea = MEA(self.config, traces, install_dir, self.rule, result_dir)
        self.filtered_traces = len(mea.filter())
        if self.filtered_traces:
            self.verdict = VERDICT_UNSAFE
        self.filtering_cpu = time.process_time() - start_time_cpu + mea.cpu_time
        self.filtering_mem = mea.memory

    def parse_line(self, line: str):
        values = line.split(";")
        self.id = values[0]
        self.rule = values[1]
        self.entrypoint = values[2]
        self.verdict = values[3]
        self.termination_reason = values[4]
        self.cpu = int(values[5])
        self.wall = int(values[6])
        self.mem = int(values[7])
        self.relevant = values[8]
        self.initial_traces = int(values[9])
        self.filtered_traces = int(values[10])
        self.work_dir = values[11]
        self.cov_lines = float(values[12])
        self.cov_funcs = float(values[13])
        self.filtering_cpu = float(values[14])

    def __str__(self):
        return ";".join([self.id, self.rule, self.entrypoint, self.verdict, self.termination_reason,
                         str(self.cpu), str(self.wall), str(self.mem), str(self.relevant), str(self.initial_traces),
                         str(self.filtered_traces),
                         self.work_dir, str(self.cov_lines), str(self.cov_funcs), str(self.filtering_cpu)])


class GlobalStatistics:
    """
    Class for collecting and printing global statistics.
    """
    def __init__(self):
        self.cpu = 0  # in seconds
        self.wall = 0  # of each verifier launch
        self.mem_average = 0  # in MB
        self.safes = 0
        self.unsafes = 0
        self.unknowns = 0
        self.et = 0
        self.filtered = 0
        self.relevant = 0

    def add_result(self, verification_result: VerificationResults):
        self.cpu += verification_result.cpu
        self.wall += verification_result.wall
        self.et += verification_result.initial_traces
        self.filtered += verification_result.filtered_traces
        if verification_result.relevant:
            self.relevant += 1
        if verification_result.verdict == VERDICT_SAFE:
            self.safes += 1
        elif verification_result.verdict == VERDICT_UNSAFE:
            self.unsafes += 1
        else:
            self.unknowns += 1
        self.mem_average += verification_result.mem

    def __add_overall(self, cpu, wall, et, filtered, relevant):
        self.cpu += cpu
        self.wall += wall
        self.et += et
        self.filtered += filtered
        self.relevant += relevant

    def sum(self, info):
        self.relevant = max(self.relevant, info.relevant)
        info.relevant = 0
        self.__add_overall(info.cpu, info.wall, info.et, info.filtered, info.relevant)
        self.mem_average = max(self.mem_average, info.mem_average)
        self.safes += info.safes
        self.unsafes += info.unsafes
        self.unknowns += info.unknowns

    def sum_memory(self):
        overall = self.safes + self.unknowns + self.unsafes
        if overall:
            self.mem_average = int(self.mem_average / overall)
        else:
            self.mem_average = 0

    def __str__(self):
        return ";".join([str(self.safes), str(self.unsafes), str(self.unknowns), str(self.relevant), str(self.et),
                         str(self.filtered), str(round(self.cpu, -3)), str(round(self.wall, -3)),
                         str(round(self.mem_average / 1000))])


class Launcher(Component):
    def __init__(self, config_file):
        self.config_file = os.path.basename(config_file).replace(JSON_EXTENSION, "")
        with open(config_file, errors='ignore') as data_file:
            config = json.load(data_file)

        super(Launcher, self).__init__(COMPONENT_LAUNCHER, config)

        # Since Launcher does not produce a lot of output and any of its failure is fatal, we can put in on stdout.
        if self.debug:
            self.output_desc = sys.stdout
        else:
            self.output_desc = subprocess.DEVNULL

        # Remember some useful directories.
        self.root_dir = os.getcwd()  # By default tool-set is run from this directory.
        self.work_dir = os.path.abspath(self.config[TAG_DIRS][TAG_DIRS_WORK])

        if self.config.get(TAG_EXPORT_HTML_ERROR_TRACES, False):
            self.result_dir_et = os.path.abspath(os.path.join(self.config[TAG_DIRS][TAG_DIRS_RESULTS],
                                                              self.__get_result_file_prefix()))
        else:
            self.result_dir_et = None
        self.install_dir = os.path.join(self.root_dir, DEFAULT_INSTALL_DIR)
        self.entrypoints_dir = os.path.join(self.root_dir, DEFAULT_ENTRYPOINTS_DIR)
        self.rules_dir = os.path.join(self.root_dir, DEFAULT_RULES_DIR)
        self.options_dir = os.path.join(self.root_dir, VERIFIER_FILES_DIR, VERIFIER_OPTIONS_DIR)
        self.patches_dir = os.path.join(self.root_dir, DEFAULT_SOURCE_PATCHES_DIR)
        self.plugin_dir = os.path.join(self.root_dir, DEFAULT_PLUGIN_DIR)

        self.backup = None  # File, in which backup copy will be placed during verification.
        self.cpu_cores = 1

        # Defines type of scheduler.
        self.scheduler = self.component_config.get(TAG_SCHEDULER)
        if not self.scheduler or self.scheduler not in SCHEDULERS:
            self.logger.error("Scheduler '{}' is not known. Choose from {}".format(self.scheduler, SCHEDULERS),
                              exc_info=True)
            exit(1)
        self.benchmark_args = self.component_config.get(TAG_BENCHMARK_ARGS, "")
        if self.scheduler == SCHEDULER_CLOUD:
            cloud_master = self.config.get(TAG_CLOUD, {}).get(TAG_CLOUD_MASTER)
            cloud_priority = self.config.get(TAG_CLOUD, {}).get(TAG_CLOUD_PRIORITY, DEFAULT_CLOUD_PRIORITY)
            self.benchmark_args = "{} --cloud --cloudMaster {} --cloudPriority {}".\
                format(self.benchmark_args, cloud_master, cloud_priority)

        # Id to separate internal files (verifier configs, patches, etc.).
        self.system_id = self.config.get(TAG_SYSTEM_ID, "")

        # Map of verifier modes to files with specific options.
        self.verifier_options = {}

    def __perform_filtering(self, result: VerificationResults, queue: multiprocessing.Queue,
                            resource_queue_filter: multiprocessing.Queue):
        wall_time_start = time.time()
        launch_directory = result.work_dir
        result.filter_traces(launch_directory, self.install_dir, self.result_dir_et)
        queue.put(result)
        resource_queue_filter.put({TAG_MEMORY_USAGE: result.filtering_mem,
                                   TAG_WALL_TIME: time.time() - wall_time_start})
        sys.exit(0)

    def __count_filter_resources(self, resource_queue_filter):
        if not resource_queue_filter.empty():
            iteration_max_memory = 0
            iteration_wall_time = 0.0
            while not resource_queue_filter.empty():
                resources = resource_queue_filter.get()
                # Those processes were running in parallel.
                iteration_max_memory += resources.get(TAG_MEMORY_USAGE, 0)
                iteration_wall_time = max(iteration_wall_time, resources.get(TAG_WALL_TIME, 0.0))
            self.mea_memory_usage = max(self.mea_memory_usage, iteration_max_memory)
            self.mea_wall_time += iteration_wall_time

    def __filter_scheduler(self, number_of_processes, output_queue: multiprocessing.Queue):
        process_pool = []
        cpu_start = time.process_time()
        for i in range(number_of_processes):
            process_pool.append(None)
        self.logger.debug("Starting scheduler for filtering with {} processes".format(number_of_processes))
        resource_queue_filter = multiprocessing.Queue()
        self.mea_memory_usage = 0
        self.mea_wall_time = 0.0
        try:
            while True:
                for i in range(number_of_processes):
                    if process_pool[i] and not process_pool[i].is_alive():
                        process_pool[i].join()
                        process_pool[i] = None
                    if not process_pool[i]:
                        if not self.mea_input_queue.empty():
                            result = self.mea_input_queue.get()
                        else:
                            continue
                        if not result:
                            raise NestedLoop
                        self.logger.info("Scheduling new filtering process: subsystem '{0}', rule '{1}', "
                                         "entrypoint '{2}'".format(result.id, result.rule, result.entrypoint))
                        process_pool[i] = multiprocessing.Process(target=self.__perform_filtering,
                                                                  name="MEA_{0}".format(i),
                                                                  args=(result, output_queue, resource_queue_filter))
                        if self.debug:
                            load = 0
                            for process in process_pool:
                                if process:
                                    load += 1
                            self.logger.debug("Scheduler for filtering load is {}%".
                                              format(round(100 * load / number_of_processes, 2)))

                        process_pool[i].start()
                sleep(BUSY_WAITING_INTERVAL * 10)
                self.__count_filter_resources(resource_queue_filter)
        except NestedLoop:
            wait_for_launches(process_pool)
            self.__count_filter_resources(resource_queue_filter)
        except:
            self.logger.error("Process for filtering results was terminated:", exc_info=True)
            kill_launches(process_pool)
        self.logger.info("Stopping filtering scheduler")
        cpu_time = time.process_time() - cpu_start
        self.logger.debug("Filtering took {0} seconds of overheads".format(cpu_time))
        scheduler_memory_usage = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
        self.mea_memory_usage += scheduler_memory_usage  # There is main thread and children processes.
        self.logger.debug("Filtering maximum memory usage: {}B".format(self.mea_memory_usage))
        self.mea_input_queue.put({TAG_MEMORY_USAGE: self.mea_memory_usage,
                                  TAG_CPU_TIME: cpu_time,
                                  TAG_WALL_TIME: self.mea_wall_time})
        sys.exit(0)

    def __create_benchmark(self, launch: VerificationTask, benchmark):
        # Create temp launch directory.
        launch_directory = os.path.abspath(tempfile.mkdtemp(dir=DEFAULT_LAUNCHES_DIR))

        # Add specific options.
        self.__resolve_property_file(benchmark, launch)
        ElementTree.SubElement(benchmark.find("rundefinition"), "option", {"name": "-setprop"}).text = \
            "output.path={0}".format(launch_directory)
        ElementTree.SubElement(benchmark.find("rundefinition"), "option", {"name": "-entryfunction"}).text = \
            launch.entrypoint
        ElementTree.SubElement(ElementTree.SubElement(benchmark, "tasks"), "include").text = launch.cil_file
        if not launch.entry_desc.optimize:
            for option in VERIFIER_OPTIONS_NOT_OPTIMIZED:
                ElementTree.SubElement(benchmark.find("rundefinition"), "option", {"name": "-setprop"}).text = option

        # Create benchmark file.
        benchmark_name = "{0}/benchmark_{1}.xml".format(DEFAULT_LAUNCHES_DIR, os.path.basename(launch_directory))
        with open(benchmark_name, "w", encoding="ascii") as fp:
            fp.write(minidom.parseString(ElementTree.tostring(benchmark)).toprettyxml(indent="    "))

        return launch_directory, benchmark_name

    def __process_single_launch_results(self, result, launch_directory, launch, queue):
        result.parse_output_dir(launch_directory, self.install_dir, self.result_dir_et)

        cov = Coverage(self)

        cov_queue = multiprocessing.Queue()
        cov_process = multiprocessing.Process(target=cov.compute_coverage, name="coverage_{}".format(launch.name),
                                              args=(self.build_results.keys(), launch_directory, cov_queue))
        cov_process.start()
        cov_process.join()  # Wait since we are already in parallel threads for each launch.
        if not cov_process.exitcode:
            if cov_queue.qsize():
                data = cov_queue.get()
                result.cov_funcs = data.get(TAG_COVERAGE_FUNCS, 0.0)
                result.cov_lines = data.get(TAG_COVERAGE_LINES, 0.0)
                result.coverage_resources[TAG_CPU_TIME] = data.get(TAG_CPU_TIME, 0.0)
                result.coverage_resources[TAG_WALL_TIME] = data.get(TAG_WALL_TIME, 0.0)
                result.coverage_resources[TAG_MEMORY_USAGE] = data.get(TAG_MEMORY_USAGE, 0)
        else:
            self.logger.warning("Coverage was not computed for subsystem {} and entrypoint {}".
                                format(launch.entry_desc.subsystem, launch.entrypoint))

        if result.initial_traces > 1:
            self.mea_input_queue.put(result)
        else:
            queue.put(result)
        sys.exit(0)

    def local_launch(self, launch: VerificationTask, benchmark, queue):
        """
        Solve verification task locally in a separated process.
        """
        (launch_directory, benchmark_name) = self.__create_benchmark(launch, benchmark)

        # Add verifier location to PATH.
        os.environ["PATH"] += os.pathsep + launch.path_to_verifier

        # Create empty result.
        result = VerificationResults(launch, self.config)
        result.work_dir = launch_directory

        # Since output directory is hardcoded in races.
        cur_cwd = os.getcwd()
        if launch.mode in [RACES, DEADLOCK]:
            shutil.move(benchmark_name, launch_directory)
            benchmark_name = os.path.basename(benchmark_name)
            os.chdir(launch_directory)

        # Verifier launch.
        subprocess.check_call("benchexec --no-compress-results -o {0} {1} {2}".
                              format(launch_directory, benchmark_name, self.benchmark_args),
                              shell=True, stderr=self.output_desc, stdout=self.output_desc)

        # Make output directory similar to the other rules.
        if launch.mode in [RACES, DEADLOCK]:
            if os.path.exists(HARDCODED_RACES_OUTPUT_DIR):
                for file in glob.glob("{}/witness*".format(HARDCODED_RACES_OUTPUT_DIR)):
                    shutil.move(file, launch_directory)
                os.rmdir(HARDCODED_RACES_OUTPUT_DIR)
            if not self.debug:
                os.remove(benchmark_name)
            os.chdir(cur_cwd)
        else:
            if not self.debug:
                os.remove(benchmark_name)

        self.__process_single_launch_results(result, launch_directory, launch, queue)

    def __get_config_mode(self, rule):
        # Determine, which configuration options should be used for this rule.
        if rule == RULE_COVERAGE:
            mode = COVERAGE
        elif rule == RULE_MEMSAFETY:
            mode = MEMSAFETY
        elif rule == RULE_RACES:
            mode = RACES
        elif rule in DEADLOCK_SUB_PROPERTIES:
            mode = rule
        elif rule == RULE_TERMINATION:
            mode = TERMINATION
        else:
            mode = UNREACHABILITY
        return mode

    def __get_tool(self, rule):
        # Determine, which tool should be used for this rule.
        if rule == RULE_COVERAGE:
            mode = COVERAGE
        elif rule == RULE_MEMSAFETY:
            mode = MEMSAFETY
        elif rule == RULE_RACES:
            mode = RACES
        elif rule == RULE_DEADLOCK:
            mode = DEADLOCK
        else:
            mode = UNREACHABILITY
        return mode

    def __get_result_file_prefix(self):
        return self.config_file + "_" + datetime.datetime.fromtimestamp(time.time()).strftime('%Y_%m_%d_%H_%M_%S')

    def __get_from_queue_into_list(self, queue, result_list):
        while not queue.empty():
            launch = queue.get()
            result_list.append(launch)
            if self.backup:
                with open(self.backup, "a") as f_report:
                    f_report.write(str(launch) + "\n")
        return result_list

    def __get_none_rule_key(self, verification_result: VerificationResults):
        return "{0}_{1}".format(verification_result.id, verification_result.entrypoint)

    def __prepare_sources(self, sources_queue: multiprocessing.Queue):
        """
        For each specified source directory the following actions can be performed:
        1. Clean.
        2. Switch to specified branch/commit.
        3. Build (with build commands as a result).
        4. Apply specified patches.
        5. Find changes of specified commits (with changed functions as a result).
        This should be performed in a separated process.
        """

        qualifier_resources = {}
        builder_resources = {}
        specific_sources = set()
        specific_functions = set()
        build_results = {}  # Information, that will be used by Preparator (source directories and build commands).
        cur_dir = os.getcwd()

        self.logger.info("Preparing source directories")
        sources = self.config.get(COMPONENT_BUILDER, {}).get(TAG_SOURCES, [])
        commits = self.config.get(TAG_COMMITS, None)

        if not sources:
            self.logger.error("Sources to be verified were not specified")
            exit(1)

        builders = {}
        for sources_config in sources:
            identifier = sources_config.get(TAG_ID)
            source_dir = sources_config.get(TAG_SOURCE_DIR)
            branch = sources_config.get(TAG_BRANCH, None)
            build_patch = sources_config.get(TAG_BUILD_PATCH, None)
            skip = sources_config.get(TAG_SKIP, False)
            build_config = sources_config.get(TAG_BUILD_CONFIG, {})
            cached_commands = sources_config.get(TAG_CACHED_COMMANDS, None)
            repository = sources_config.get(TAG_REPOSITORY, None)
            build_commands = os.path.join(cur_dir, "cmds_{}.json".format(re.sub("\W", "_", identifier)))

            if not source_dir or not os.path.exists(source_dir):
                self.logger.error("Source directory '{}' does not exist".format(source_dir))
                exit(1)

            if build_config:
                build_results[source_dir] = build_commands

            if skip:
                self.logger.debug("Skipping building of sources '{}' (directory {})".format(identifier, source_dir))
                if build_config:
                    if not (cached_commands and os.path.exists(cached_commands)):
                        self.logger.error("Cached build commands were not specified for sources '{}', "
                                          "preparation of which was skipped".format(identifier))
                        exit(1)
                    shutil.copy(cached_commands, build_commands)
                continue
            else:
                self.logger.debug("Building of sources '{}' (directory {})".format(identifier, source_dir))

            builder = Builder(self.install_dir, self.config, source_dir, build_config, repository)
            builder.clean()

            if branch:
                builder.change_branch(branch)

            if build_patch:
                build_patch = self.__get_file_for_system(self.patches_dir, build_patch)
                builder.patch(build_patch)

            builders[builder] = None
            if build_config:
                if cached_commands and os.path.exists(cached_commands):
                    self.logger.debug("Taking build commands from cached file {}".format(cached_commands))
                    shutil.copy(cached_commands, build_commands)
                else:
                    self.logger.debug("Generating build commands in file {}".format(build_commands))
                    builders[builder] = build_commands

        for sources_config in sources:
            source_dir = sources_config.get(TAG_SOURCE_DIR)
            patches = sources_config.get(TAG_PATCH, [])

            builder = None
            for tmp_builder in builders.keys():
                if tmp_builder.source_dir == source_dir:
                    builder = tmp_builder
                    break

            if builder:
                build_commands = builders[builder]
                if build_commands:
                    builder.build(build_commands)
                builder_resources = self.add_resources(builder.get_component_full_stats(), builder_resources)

                if commits:
                    if not builder.repository:
                        self.logger.error("Cannot check commits without repository")
                        exit(1)
                    self.logger.debug("Finding all entrypoints for specified commits {}".format(commits))
                    qualifier = Qualifier(builder,
                                          self.__get_files_for_system(self.entrypoints_dir, "*" + JSON_EXTENSION))
                    specific_sources_new, specific_functions_new = qualifier.analyse_commits(commits)
                    specific_functions_new = qualifier.find_functions(specific_functions_new)
                    specific_sources = specific_sources.union(specific_sources_new)
                    specific_functions = specific_functions.union(specific_functions_new)
                    qualifier_resources = self.add_resources(qualifier.stop(), qualifier_resources)

                if patches:
                    for patch in patches:
                        self.logger.debug("Apply patch {}".format(patch))
                        patch = self.__get_file_for_system(self.patches_dir, patch)
                        builder.patch(patch)

        sources_queue.put({
            SOURCE_QUEUE_QUALIFIER_RESOURCES: qualifier_resources,
            SOURCE_QUEUE_BUILDER_RESOURCES: builder_resources,
            SOURCE_QUEUE_FILES: specific_sources,
            SOURCE_QUEUE_FUNCTIONS: specific_functions,
            SOURCE_QUEUE_RESULTS: build_results
        })
        sys.exit(0)

    def __get_verifier_options_file_name(self, file_name: str) -> str:
        abs_path = self.__get_file_for_system(self.options_dir, re.sub("\W", "_", file_name) + JSON_EXTENSION)
        if not os.path.exists(abs_path):
            # Some rule may not be needed for for systems.
            return ""
        return abs_path

    def __resolve_property_file(self, rundefinition: ElementTree.Element, launch: VerificationTask) -> None:
        """
        Property file is resolved in the following way:
         - rule specific automaton (*.spc file);
         - based on launch mode (only for unreachability and memsafety).
        Note, that any manually specified property files in options file will be added as well.
        :param rundefinition: definition of a single run in BenchExec format;
        :param launch: verification task to be checked;
        """
        automaton_file = self.__get_file_for_system(os.path.join(self.root_dir, VERIFIER_FILES_DIR,
                                                                 VERIFIER_PROPERTIES_DIR), launch.rule + ".spc")
        if automaton_file:
            automaton_file = os.path.join(VERIFIER_PROPERTIES_DIR, os.path.basename(automaton_file))
            ElementTree.SubElement(rundefinition, "option", {"name": "-spec"}).text = automaton_file
        else:
            if launch.mode == MEMSAFETY:
                ElementTree.SubElement(rundefinition, "option", {"name": "-spec"}).text = DEFAULT_PROPERTY_MEMSAFETY
            if launch.mode == UNREACHABILITY:
                ElementTree.SubElement(rundefinition, "option", {"name": "-spec"}).text = \
                    DEFAULT_PROPERTY_UNREACHABILITY

    def __parse_verifier_options(self, file_name: str, rundefinition: ElementTree.Element) -> None:
        if file_name in self.verifier_options.keys():
            abs_path = self.verifier_options[file_name]
        else:
            abs_path = self.__get_verifier_options_file_name(file_name)
        if not os.path.exists(abs_path):
            # No new options for specific rule and system id.
            return
        with open(abs_path, "r", errors='ignore') as fh:
            content = json.load(fh)
            for name, values in content.items():
                if values:
                    for value in values:
                        ElementTree.SubElement(rundefinition, "option", {"name": name}).text = value
                else:
                    ElementTree.SubElement(rundefinition, "option", {"name": name})

    def __process_single_group(self, mode, launches, time_limit, memory_limit, core_limit, heap_limit,
                               internal_time_limit, queue):
        # Prepare benchmark file for the whole group.
        benchmark_cur = ElementTree.Element("benchmark", {
            "tool": CPACHECKER,
            "timelimit": str(time_limit),
            "memlimit": str(memory_limit) + "GB",
            "cpuCores": str(core_limit)
        })
        ElementTree.SubElement(benchmark_cur, "resultfiles").text = "**/*"
        ElementTree.SubElement(benchmark_cur, "requiredfiles").text = "properties/*"
        for launch in launches:
            name = "{}_{}_{}".format(launch.entrypoint, launch.rule, os.path.basename(launch.cil_file))
            rundefinition = ElementTree.SubElement(benchmark_cur, "rundefinition", {"name": name})
            ElementTree.SubElement(rundefinition, "option", {"name": "-heap"}).text = "{}m".format(heap_limit)
            ElementTree.SubElement(rundefinition, "option", {"name": "-timelimit"}).text = str(
                internal_time_limit)
            self.__resolve_property_file(rundefinition, launch)
            self.__parse_verifier_options(VERIFIER_OPTIONS_COMMON, rundefinition)
            if launch.rule in DEADLOCK_SUB_PROPERTIES:
                mode_for_options = launch.rule
            else:
                mode_for_options = launch.mode
            self.__parse_verifier_options(mode_for_options, rundefinition)
            ElementTree.SubElement(rundefinition, "option", {"name": "-entryfunction"}).text = \
                launch.entrypoint
            if not launch.entry_desc.optimize:
                for option in VERIFIER_OPTIONS_NOT_OPTIMIZED:
                    ElementTree.SubElement(rundefinition, "option", {"name": "-setprop"}).text = option
            ElementTree.SubElement(ElementTree.SubElement(rundefinition, "tasks"),
                                   "include").text = os.path.relpath(launch.cil_file)
        benchmark_name = "{0}/benchmark_{1}.xml".format(DEFAULT_LAUNCHES_DIR, mode)
        with open(benchmark_name, "w", encoding="ascii") as fp:
            fp.write(minidom.parseString(ElementTree.tostring(benchmark_cur)).toprettyxml(indent="    "))

        # Create temp directory for group.
        group_directory = os.path.abspath(tempfile.mkdtemp(dir=DEFAULT_LAUNCHES_DIR))

        # Creating links.
        cil_abs_dir = os.path.join(os.getcwd(), DEFAULT_CIL_DIR)
        properties_abs_dir = os.path.join(self.work_dir, VERIFIER_PROPERTIES_DIR)
        benchmark_abs_dir = os.path.abspath(benchmark_name)
        cil_rel_dir = DEFAULT_CIL_DIR
        properties_rel_dir = VERIFIER_PROPERTIES_DIR
        benchmark_rel_dir = os.path.basename(benchmark_name)

        # Launch from CPAchecker directory
        verifier_dir = os.path.join(self.install_dir, DEFAULT_CPACHECKER_CLOUD[mode])
        cur_dir = os.getcwd()
        os.chdir(verifier_dir)

        os.makedirs(cil_rel_dir, exist_ok=True)
        os.makedirs(properties_rel_dir, exist_ok=True)
        for file in glob.glob(os.path.join(cil_abs_dir, "*")):
            if os.path.isfile(file):
                shutil.copy(file, cil_rel_dir)
        for file in glob.glob(os.path.join(properties_abs_dir, "*")):
            if os.path.isfile(file):
                shutil.copy(file, properties_rel_dir)

        if os.path.islink(benchmark_rel_dir):
            os.unlink(benchmark_rel_dir)
        os.symlink(benchmark_abs_dir, benchmark_rel_dir)

        log_file_name = os.path.join(group_directory, CLOUD_BENCHMARK_LOG)
        with open(log_file_name, 'w') as f_log:
            # Launch group.
            command = "python3 scripts/benchmark.py --no-compress-results -o {0} --container {1} {2}". \
                format(group_directory, os.path.basename(benchmark_name), self.benchmark_args)
            self.logger.debug("Launching benchmark: {}".format(command))
            subprocess.check_call(command, shell=True, stderr=f_log, stdout=f_log)

        # Process results (in parallel -- we assume, that the master host is free).
        process_pool = []
        for i in range(self.cpu_cores):
            process_pool.append(None)
        for launch in launches:
            files = glob.glob(os.path.join(group_directory, "*.logfiles", "{0}_{2}_{1}.{3}*".
                                           format(launch.entrypoint, os.path.basename(launch.cil_file),
                                                  launch.rule, os.path.basename(launch.cil_file))))
            launch_dir = os.path.abspath(tempfile.mkdtemp(dir=group_directory))
            for file in files:
                if file.endswith(".i.files"):
                    for root, dirs, files_in in os.walk(file):
                        for name in files_in:
                            file = os.path.join(root, name)
                            shutil.move(file, launch_dir)
                if file.endswith(".log"):
                    shutil.move(file, os.path.join(launch_dir, "log.txt"))
            xml_files = glob.glob(os.path.join(group_directory, 'benchmark*results.{}_{}_{}.xml'.format(
                launch.entrypoint, launch.rule, os.path.basename(launch.cil_file)
            )))
            if not xml_files:
                self.logger.warning("There is no xml file for launch {}".format(launch))
            else:
                shutil.move(xml_files[0], launch_dir)

            result = VerificationResults(launch, self.config)
            result.work_dir = launch_dir

            try:
                while True:
                    for i in range(self.cpu_cores):
                        if process_pool[i] and not process_pool[i].is_alive():
                            process_pool[i].join()
                            process_pool[i] = None
                        if not process_pool[i]:
                            process_pool[i] = multiprocessing.Process(target=self.__process_single_launch_results,
                                                              name=result.entrypoint,
                                                              args=(result, launch_dir, launch, queue))
                            process_pool[i].start()
                            raise NestedLoop
                    sleep(BUSY_WAITING_INTERVAL)
            except NestedLoop:
                pass
            except:
                self.logger.error("Error during processing results:", exc_info=True)
                kill_launches(process_pool)
        wait_for_launches(process_pool)
        os.chdir(cur_dir)

    def __get_groups_with_established_connections(self):
        result = set()
        log_files = glob.glob(os.path.join(self.work_dir, DEFAULT_LAUNCHES_DIR, "*", CLOUD_BENCHMARK_LOG))
        for log_file in log_files:
            if os.path.exists(log_file):
                with open(log_file, errors='ignore') as f_log:
                    for line in f_log.readlines():
                        res = re.search(r'INFO	BenchmarkClient:OutputHandler\$1\.onSuccess	Received run result for run 1 of', line)
                        if res:
                            group_id = os.path.basename(os.path.dirname(log_file))
                            result.add(group_id)
                            break
        return result

    def __upload_results(self, uploader_config, result_file):
        server = uploader_config.get(TAG_UPLOADER_SERVER)
        identifier = uploader_config.get(TAG_UPLOADER_IDENTIFIER)
        user = uploader_config.get(TAG_UPLOADER_USER)
        password = uploader_config.get(TAG_UPLOADER_PASSWORD)
        is_parent = uploader_config.get(TAG_UPLOADER_PARENT_ID, False)
        predefined_name = uploader_config.get(TAG_NAME, None)
        if not server:
            self.logger.error("Server was not provided for uploading results, skipping it.")
            return
        if not identifier:
            self.logger.error("Job identifier was not provided for uploading results, skipping it.")
            return
        if not user:
            self.logger.error("User name was not provided for uploading results, skipping it.")
            return
        self.logger.info("Uploading results into server {} with identifier {}".format(server, identifier))
        uploader = self.get_tool_path(DEFAULT_TOOL_PATH[UPLOADER])
        uploader_python_path = os.path.abspath(os.path.join(os.path.dirname(uploader), os.path.pardir))
        commits = self.config.get(TAG_COMMITS)
        if commits:
            commit = commits[0]
            res = re.search(r'(\w+)\.\.(\w+)', commit)
            if res:
                commit = res.group(2)
                commits = commit[:7]
        timestamp = datetime.datetime.fromtimestamp(time.time()).strftime('%Y_%m_%d_%H_%M_%S')
        if predefined_name:
            job_name = predefined_name.replace(TIMESTAMP_PATTERN, timestamp)
            job_name = job_name.replace(COMMIT_PATTERN, str(commits))
        elif commits:
            job_name = "{}: {} ({})".format(self.config_file, commits, timestamp)
        else:
            job_name = "{} ({})".format(self.config_file, timestamp)
        self.logger.debug("Using name '{}' for uploaded report".format(job_name))
        command = "PYTHONPATH={} {} {} --host='{}' --username='{}' --password='{}' --archive='{}' --name='{}'".\
            format(uploader_python_path, uploader, identifier, server, user, password, result_file, job_name)
        if is_parent:
            command = "{} --copy".format(command)
        try:
            subprocess.check_call(command, shell=True)
        except:
            self.logger.warning("Error on uploading of report archive '{}' via command '{}':\n".
                                format(result_file, command), exc_info=True)
        self.logger.info("Results were successfully uploaded into the server: {}/jobs".format(server))

    def __get_file_for_system(self, prefix: str, file: str) -> str:
        if not file:
            return ""
        plugin_dir = os.path.join(self.plugin_dir, self.system_id, os.path.relpath(prefix, self.root_dir))
        if self.system_id:
            new_path = os.path.join(plugin_dir, file)
            if os.path.exists(new_path):
                return new_path
        new_path = os.path.join(prefix, file)
        if os.path.exists(new_path):
            return new_path
        self.logger.debug("Cannot find file {} neither in basic directory {} nor in plugin directory {}".
                          format(file, prefix, plugin_dir))
        return ""

    def __get_files_for_system(self, prefix: str, pattern: str) -> list:
        plugin_dir = os.path.join(self.plugin_dir, self.system_id, os.path.relpath(prefix, self.root_dir))
        if self.system_id:
            result = glob.glob(os.path.join(plugin_dir, pattern))
            if result:
                return result
        result = glob.glob(os.path.join(prefix, pattern))
        if result:
            return result
        self.logger.debug("Cannot find any files by pattern {} neither in basic directory {} nor in plugin directory {}"
                          .format(pattern, prefix, plugin_dir))
        return []

    def launch(self):
        # Process common directories.
        results_dir = os.path.abspath(self.config[TAG_DIRS][TAG_DIRS_RESULTS])

        results = []  # Verification results.
        backup_read = self.component_config.get(TAG_BACKUP_READ, False)
        self.logger.debug("Clearing old working directory '{}'".format(self.work_dir))
        is_cached = self.config.get(TAG_CACHED, False) or backup_read
        if not is_cached:
            shutil.rmtree(self.work_dir, ignore_errors=True)

        self.logger.debug("Create new working directory tree")
        os.makedirs(self.work_dir, exist_ok=True)
        os.chdir(self.work_dir)
        if is_cached:
            shutil.rmtree(DEFAULT_MAIN_DIR, ignore_errors=True)
            if not backup_read:
                shutil.rmtree(DEFAULT_LAUNCHES_DIR, ignore_errors=True)
            shutil.rmtree(DEFAULT_EXPORT_DIR, ignore_errors=True)
            shutil.rmtree(VERIFIER_PROPERTIES_DIR, ignore_errors=True)
        os.makedirs(VERIFIER_PROPERTIES_DIR, exist_ok=True)
        os.makedirs(DEFAULT_CIL_DIR, exist_ok=True)
        os.makedirs(DEFAULT_MAIN_DIR, exist_ok=True)
        os.makedirs(DEFAULT_LAUNCHES_DIR, exist_ok=True)
        os.makedirs(DEFAULT_PREPROCESS_DIR, exist_ok=True)
        os.makedirs(DEFAULT_EXPORT_DIR, exist_ok=True)
        if not os.path.exists(results_dir):
            os.makedirs(results_dir, exist_ok=True)

        self.logger.debug("Check resource limitations")
        max_cores = multiprocessing.cpu_count()
        self.cpu_cores = max_cores
        self.logger.debug("Machine has {} CPU cores".format(max_cores))
        max_memory = int(int(subprocess.check_output("free -m", shell=True).splitlines()[1].split()[1]) / 1000)
        self.logger.debug("Machine has {}GB of RAM".format(max_memory))

        if self.component_config.get(TAG_BACKUP_WRITE, False):
            self.backup = "{0}{1}.csv".format(DEFAULT_BACKUP_PREFIX, self.__get_result_file_prefix())

        resource_limits = self.component_config.get(TAG_RESOURCE_LIMITATIONS)
        memory_limit = resource_limits.get(TAG_LIMIT_MEMORY, max_memory)
        if not self.scheduler == SCHEDULER_CLOUD and max_memory < memory_limit:
            self.logger.error("There is not enough memory to start scheduler: {0}GB are required, "
                              "whereas only {1}GB are available.".format(memory_limit, max_memory))
            exit(1)
        heap_limit = int(memory_limit * 1000 * 13 / 15)  # Basic conversion to get Java heap size (in MB)

        time_limit = resource_limits[TAG_LIMIT_CPU_TIME]

        statistics_time = self.component_config.get(TAG_STATISTICS_TIME, DEFAULT_TIME_FOR_STATISTICS)
        if statistics_time >= time_limit:
            self.logger.warning("Specified time for printing statistics {}s is bigger than overall time limit. "
                                "Ignoring statistics time".format(statistics_time))
            statistics_time = 0
        internal_time_limit = time_limit - statistics_time

        core_limit = resource_limits.get(TAG_LIMIT_CPU_CORES, max_cores)
        if not self.scheduler == SCHEDULER_CLOUD and max_cores < core_limit:
            self.logger.error("There is not enough CPU cores to start scheduler: {0} are required, "
                              "whereas only {1} are available.".format(core_limit, max_cores))
            exit(1)

        specific_functions = set(self.config.get(TAG_CALLERS, set()))
        specific_sources = set()
        qualifier_resources = {}
        builder_resources = {}
        if self.config.get(TAG_COMMITS) and specific_functions:
            self.logger.error("Sanity check failed: it is forbidden to specify both callers and commits tags")
            exit(1)

        proc_by_memory = int(max_memory / memory_limit)
        proc_by_cores = int(max_cores / core_limit)
        parallel_launches = int(self.component_config.get(TAG_PARALLEL_LAUNCHES, 0))
        if parallel_launches < 0:
            self.logger.error("Incorrect value for number of parallel launches: {}".format(parallel_launches))
            exit(1)
        if not parallel_launches:
            number_of_processes = min(proc_by_memory, proc_by_cores)
        else:
            # Careful with this number: if it is too big, memory may be exhausted.
            number_of_processes = parallel_launches
        self.logger.debug("Max parallel verifier launches on current host: {}".format(number_of_processes))
        self.logger.debug("Each verifier launch will be limited to {0}GB of RAM, "
                          "{1} seconds of CPU time and {2} CPU cores".format(memory_limit, time_limit, core_limit))

        # We need to perform sanity checks before complex operation of building.
        rules = self.config.get("rules")
        if not rules:
            sys.exit("No rules to be checked were specified")

        ep_desc_files = self.config.get(TAG_ENTRYPOINTS_DESC)
        entrypoints_desc = set()
        if not ep_desc_files:
            sys.exit("No file with description of entry points to be checked were specified")
        else:
            for group in ep_desc_files:
                self.logger.debug("Processing given group of files: {}".format(group))
                # Wildcards are supported here.
                files = self.__get_files_for_system(self.entrypoints_dir, group + JSON_EXTENSION)
                if not files:
                    self.logger.warning("No file with description of entry points were found for group '{}'. "
                                        "This group will be ignored.".format(group))
                for file in files:
                    self.logger.debug("Processing file with entry point description '{}'".format(file))
                    identifier = os.path.basename(file)[:-len(JSON_EXTENSION)]
                    entrypoints_desc.add(EntryPointDesc(file, identifier))
            if not entrypoints_desc:
                sys.exit("No file with description of entry points to be checked were found")

        for mode, file in self.component_config.get(TAG_VERIFIER_OPTIONS, {}).items():
            if mode not in VERIFIER_MODES:
                sys.exit("Cannot set options for verifier mode '{}'".format(mode))
            path = self.__get_verifier_options_file_name(str(file))
            if path:
                self.verifier_options[mode] = path
                self.logger.debug("Using verifier options from file '{}' for verification mode '{}'".format(path, mode))
            else:
                sys.exit("File with verifier options '{}' for verification mode '{}' does not exist".format(file, mode))

        # Process sources in separate process.
        sources_queue = multiprocessing.Queue()
        sources_process = multiprocessing.Process(target=self.__prepare_sources, name="sources",
                                                  args=(sources_queue, ))
        sources_process.start()
        sources_process.join()  # Wait here since this information may reduce future preparation work.

        if not sources_process.exitcode:
            if sources_queue.qsize():
                data = sources_queue.get()
                if not specific_functions:
                    specific_functions = data.get(SOURCE_QUEUE_FUNCTIONS)
                specific_sources = data.get(SOURCE_QUEUE_FILES)
                qualifier_resources = data.get(SOURCE_QUEUE_QUALIFIER_RESOURCES)
                builder_resources = data.get(SOURCE_QUEUE_BUILDER_RESOURCES)
                self.build_results = data.get(SOURCE_QUEUE_RESULTS)
        else:
            self.logger.error("Source directories were not prepared")
            exit(sources_process.exitcode)

        if specific_functions:
            static_callers = set()
            for func in specific_functions:
                static_callers.add(func + STATIC_SUFFIX)
            specific_functions.update(static_callers)

        self.logger.info("Preparing verification tasks based on the given configuration")
        preparator_processes = self.config.get(COMPONENT_PREPARATOR, {}).get(TAG_PROCESSES, max_cores)
        self.logger.debug("Starting scheduler for verification tasks preparation with {} processes".
                          format(preparator_processes))

        find_coverage = self.config.get(TAG_FIND_COVERAGE, True)
        if find_coverage:
            if RULE_COVERAGE in rules and len(rules) > 1:
                rules.remove(RULE_COVERAGE)
            if RULE_COVERAGE not in rules:
                self.logger.debug("Adding auxiliary rule 'cov' to find coverage")
                is_other = False
                for rule in rules:
                    if rule not in [RULE_RACES, RULE_DEADLOCK]:
                        is_other = True
                if is_other:
                    rules.append(RULE_COV_AUX_OTHER)
                if RULE_RACES in rules or RULE_DEADLOCK in rules:
                    rules.append(RULE_COV_AUX_RACES)

        preparator_start_wall = time.time()
        resource_queue = multiprocessing.Queue()
        launches = deque()
        process_pool = []
        for i in range(preparator_processes):
            process_pool.append(None)

        preparation_config_file = self.__get_file_for_system(
            os.path.join(self.root_dir, DEFAULT_PREPARATION_PATCHES_DIR),
            self.config.get(TAG_PREPARATION_CONFIG, DEFAULT_PREPARATION_CONFIG))
        if preparation_config_file:
            with open(preparation_config_file) as fd:
                preparation_config = json.load(fd)
        else:
            preparation_config = {}

        for entry_desc in entrypoints_desc:
            if specific_sources:
                is_skip = True
                for file in specific_sources:
                    if entry_desc.subsystem in file:
                        is_skip = False
                        break
                if is_skip:
                    self.logger.debug("Skipping subsystem '{}' because it does not relate with the checking commits".
                                      format(entry_desc.subsystem))
                    continue
            main_generator = MainGenerator(self.config, entry_desc.file)
            main_generator.process_sources()
            for rule in rules:
                strategy = main_generator.get_strategy(rule)
                if rule in [RULE_COV_AUX_OTHER, RULE_COV_AUX_RACES]:
                    rule = RULE_COVERAGE
                mode = self.__get_tool(rule)
                main_file_name = os.path.join(DEFAULT_MAIN_DIR, "{0}_{1}.c".format(entry_desc.short_name, strategy))
                entrypoints = main_generator.generate_main(strategy, main_file_name)
                model = self.__get_file_for_system(self.rules_dir, "{0}.c".format(rule))
                if not model:
                    self.logger.debug("There is no model file for rule {}".format(rule))
                common_file = self.__get_file_for_system(self.rules_dir, COMMON_HEADER_FOR_RULES)
                cil_file = os.path.abspath(os.path.join(DEFAULT_CIL_DIR, "{0}_{1}_{2}.i".format(entry_desc.short_name,
                                                                                                rule, strategy)))
                try:
                    while True:
                        for i in range(preparator_processes):
                            if process_pool[i] and not process_pool[i].is_alive():
                                process_pool[i].join()
                                process_pool[i] = None
                            if not process_pool[i]:
                                if is_cached and os.path.exists(cil_file):
                                    self.logger.debug("Using cached CIL-file {0}".format(cil_file))
                                else:
                                    self.logger.debug("Generating verification task {0} for entrypoints {1}, rule {2}".
                                                      format(cil_file, entry_desc.id, rule))
                                    preparator = Preparator(self.install_dir, self.config,
                                                            subdirectory_pattern=entry_desc.subsystem, model=model,
                                                            main_file=main_file_name, output_file=cil_file,
                                                            preparation_config=preparation_config,
                                                            common_file=common_file, build_results=self.build_results)
                                    process_pool[i] = multiprocessing.Process(target=preparator.prepare_task,
                                                                              name=cil_file, args=(resource_queue,))
                                    process_pool[i].start()
                                raise NestedLoop
                        sleep(BUSY_WAITING_INTERVAL)
                except NestedLoop:
                    pass
                except:
                    self.logger.error("Could not prepare verification task:", exc_info=True)
                    kill_launches(process_pool)
                for entrypoint in entrypoints:
                    path_to_verifier = self.get_tool_path(DEFAULT_TOOL_PATH[CPACHECKER][mode],
                                                          self.config.get(TAG_TOOLS, {}).get(CPACHECKER, {}).get(mode))
                    if rule == RULE_DEADLOCK:
                        # Here we perform several launches per each entry_desc.
                        for rule_aux in DEADLOCK_SUB_PROPERTIES:
                            launches.append(VerificationTask(entry_desc, rule_aux, entrypoint, path_to_verifier,
                                                             cil_file))
                    elif rule == RULE_RACES:
                        launches.append(VerificationTask(entry_desc, rule, entrypoint, path_to_verifier, cil_file))
                    else:
                        # Either take only specified callers or all of them.
                        if not specific_functions or \
                                entrypoint.replace(ENTRY_POINT_SUFFIX, "") in specific_functions or \
                                entrypoint == DEFAULT_MAIN:
                            launches.append(VerificationTask(entry_desc, rule, entrypoint, path_to_verifier, cil_file))
        wait_for_launches(process_pool)

        # Filter problem launches
        removed_launches = []
        added_launches = {}
        for launch in launches:
            if not os.path.exists(launch.cil_file) or os.path.getsize(launch.cil_file) == 0:
                removed_launches.append(launch)
                # Check for several CIL files.
                cil_files = glob.glob(launch.cil_file + "*")
                if not cil_files:
                    # Nothing was prepared -- error during preparation.
                    self.logger.warning("The file {0} was not found, skip the corresponding launch".
                                        format(launch.cil_file))
                else:
                    # Several CIL files were found - need to multiply this launch for each CIL file.
                    cil_files.sort()
                    added_launches[launch] = cil_files

        for launch in removed_launches:
            launches.remove(launch)

        for launch, cil_files in added_launches.items():
            for cil_file in cil_files:
                new_launch = launch.copy()
                new_launch.cil_file = cil_file
                # TODO: add this file id (cil_file[len(new_launch.cil_file):]) as a launch parameter
                launches.append(new_launch)

        if not launches:
            self.logger.info("The given configuration does not require any launches "
                             "(the changes are irrelevant for checked subsystems)")

        counter = 1
        preparation_memory_usage = 0
        preparation_cpu_time = time.process_time() - self.start_cpu_time
        preparation_memory_usage_all = []
        preparator_unknowns = []
        while not resource_queue.empty():
            resources = resource_queue.get()
            preparator_wall_time = resources.get(TAG_WALL_TIME, 0.0)
            preparator_cpu_time = resources.get(TAG_CPU_TIME, 0.0)
            preparator_memory = resources.get(TAG_MEMORY_USAGE, 0)
            preparation_memory_usage_all.append(preparator_memory)
            preparation_cpu_time += preparator_cpu_time
            if TAG_LOG_FILE in resources:
                cil_file = resources.get(TAG_CIL_FILE, "")
                attrs = list()
                if cil_file:
                    res = re.search(r"(\w+)_([^_]+)_(\w+)\.i", os.path.basename(cil_file))
                    if res:
                        attrs = [
                            {"name": "Subsystem", "value": res.group(1)},
                            {"name": "Rule specification", "value": res.group(2)},
                            {"name": "Strategy", "value": res.group(3)},
                        ]

                for log in resources.get(TAG_LOG_FILE):
                    preparator_unknowns.append({
                        TAG_LOG_FILE: log,
                        TAG_CPU_TIME: round(preparator_cpu_time * 1000),
                        TAG_WALL_TIME: round(preparator_wall_time * 1000),
                        TAG_MEMORY_USAGE: preparator_memory,
                        TAG_ATTRS: attrs
                    })

        for memory_usage in sorted(preparation_memory_usage_all):
            preparation_memory_usage += memory_usage
            counter += 1
            if counter > preparator_processes:
                break

        if find_coverage:
            for rule in [RULE_COV_AUX_OTHER, RULE_COV_AUX_RACES]:
                if rule in rules:
                    rules.remove(rule)
            if RULE_COVERAGE not in rules:
                rules.append(RULE_COVERAGE)

        if backup_read:
            self.logger.info("Restoring from backup copy")
            backup_files = glob.glob(os.path.join(self.work_dir, "{}*".format(DEFAULT_BACKUP_PREFIX)))
            for file in backup_files:
                with open(file, "r", errors='ignore') as f_res:
                    for line in f_res.readlines():
                        result = VerificationResults(None, self.config)
                        result.parse_line(line)
                        for launch in launches:
                            if result.is_equal(launch):
                                results.append(result)
                                launches.remove(launch)
                                break
                os.remove(file)
            if self.backup:
                with open(self.backup, "a") as f_report:
                    for result in results:
                        f_report.write(str(result) + "\n")
            if len(results):
                self.logger.info("Successfully restored {} results".format(len(results)))
            else:
                self.logger.info("No results were restored")

        self.logger.info("Preparation of verification tasks has been completed")
        preparation_wall_time = time.time() - preparator_start_wall
        self.logger.debug("Preparation wall time: {} seconds".format(round(preparation_wall_time, 2)))
        self.logger.debug("Preparation CPU time: {} seconds".format(round(preparation_cpu_time, 2)))
        self.logger.debug("Preparation memory usage: {} Mb".format(round(preparation_memory_usage / 2**20, 2)))
        self.logger.info("Starting to solve verification tasks")
        self.logger.info("Expected number of verifier launches is {}".format(len(launches)))

        # Prepare BenchExec commands.
        path_to_benchexec = self.get_tool_path(DEFAULT_TOOL_PATH[BENCHEXEC],
                                               self.config.get(TAG_TOOLS, {}).get(BENCHEXEC))
        self.logger.debug("Using BenchExec, found in: '{0}'".format(path_to_benchexec))
        os.environ["PATH"] += os.pathsep + path_to_benchexec
        benchmark = {}
        for mode in VERIFIER_MODES:
            # Specify resource limitations.
            benchmark[mode] = ElementTree.Element("benchmark", {
                "tool": CPACHECKER,
                "timelimit": str(time_limit),
                "memlimit": str(memory_limit) + "GB",
                # TODO: option 'cpuCores' does not work in BenchExec
            })
            rundefinition = ElementTree.SubElement(benchmark[mode], "rundefinition")
            ElementTree.SubElement(rundefinition, "option", {"name": "-heap"}).text = "{}m".format(heap_limit)
            ElementTree.SubElement(rundefinition, "option", {"name": "-timelimit"}).text = str(internal_time_limit)

            # Create links to the properties.
            for file in glob.glob(os.path.join(self.root_dir, VERIFIER_FILES_DIR, VERIFIER_PROPERTIES_DIR, "*")):
                if os.path.isfile(file):
                    shutil.copy(file, VERIFIER_PROPERTIES_DIR)
            if self.system_id:
                for file in glob.glob(os.path.join(self.plugin_dir, self.system_id, VERIFIER_FILES_DIR,
                                                   VERIFIER_PROPERTIES_DIR, "*")):
                    if os.path.isfile(file):
                        shutil.copy(file, VERIFIER_PROPERTIES_DIR)

            # Get options from files.
            self.__parse_verifier_options(VERIFIER_OPTIONS_COMMON, rundefinition)
            self.__parse_verifier_options(mode, rundefinition)

        self.logger.debug("Starting scheduler for verifier launches with {} processes".format(number_of_processes))
        counter = 1
        number_of_launches = len(launches)
        queue = multiprocessing.Queue()
        self.mea_input_queue = multiprocessing.Queue()
        if self.scheduler == SCHEDULER_CLOUD:
            mea_processes = self.config.get(COMPONENT_MEA, {}).get(TAG_PARALLEL_LAUNCHES, self.cpu_cores)
        else:
            mea_processes = max(1, max_cores - number_of_processes)
        filtering_process = multiprocessing.Process(target=self.__filter_scheduler, name="MEA",
                                                    args=(mea_processes, queue))
        filtering_process.start()

        if self.scheduler == SCHEDULER_CLOUD:
            launch_groups = dict()
            for launch in launches:
                mode = self.__get_config_mode(launch.rule)
                if mode == COVERAGE:
                    mode = COVERAGE
                if mode in DEADLOCK_SUB_PROPERTIES:
                    mode = RACES
                if mode in launch_groups:
                    launch_groups[mode].append(launch)
                else:
                    launch_groups[mode] = [launch]
            del launches
            self.logger.info("Divided all tasks into {} group(s) for solving on cloud".format(len(launch_groups)))
            process_pool = list()
            for mode, launches in launch_groups.items():
                process_single_group = multiprocessing.Process(target=self.__process_single_group, name=mode,
                                                               args=(mode, launches, time_limit, memory_limit,
                                                                     core_limit, heap_limit, internal_time_limit,
                                                                     queue))
                process_single_group.start()
                process_pool.append(process_single_group)
            connection_established = False
            solving_groups = set()
            while True:
                self.__get_from_queue_into_list(queue, results)
                if not connection_established:
                    new_groups = self.__get_groups_with_established_connections()
                    if not new_groups <= solving_groups:
                        for group in new_groups:
                            if group not in solving_groups:
                                solving_groups.add(group)
                                self.logger.info("Established connection to group {}".format(len(solving_groups)))
                        if len(solving_groups) == len(launch_groups):
                            self.logger.info("Connection to all group(s) has been established")
                            connection_established = True
                if not any(p.is_alive() for p in process_pool):
                    break
                sleep(BUSY_WAITING_INTERVAL)
        elif self.scheduler == SCHEDULER_LOCAL:
            process_pool = []
            for i in range(number_of_processes):
                process_pool.append(None)
            try:
                while True:
                    for i in range(number_of_processes):
                        if process_pool[i] and not process_pool[i].is_alive():
                            process_pool[i].join()
                            process_pool[i] = None
                            self.__get_from_queue_into_list(queue, results)
                        if not process_pool[i]:
                            launch = launches.popleft()
                            percent = 100 - 100 * counter / number_of_launches
                            self.logger.info("Scheduling new launch: subsystem '{0}', rule '{1}', entrypoint '{2}' "
                                             "({3}% remains)".format(launch.entry_desc.subsystem, launch.rule,
                                                                     launch.entrypoint, round(percent, 2)))
                            counter += 1
                            mode = self.__get_config_mode(launch.rule)
                            process_pool[i] = multiprocessing.Process(target=self.local_launch, name=launch.name,
                                                                      args=(launch, benchmark[mode], queue))
                            process_pool[i].start()
                            if len(launches) == 0:
                                raise NestedLoop
                    sleep(BUSY_WAITING_INTERVAL)
            except NestedLoop:
                # All entry points has been checked.
                wait_for_launches(process_pool)
                self.__get_from_queue_into_list(queue, results)
            except:
                self.logger.error("Process scheduler was terminated:", exc_info=True)
                filtering_process.terminate()
                kill_launches(process_pool)
                exit(1)
        else:
            raise NotImplementedError

        self.logger.info("All launches have been completed")
        self.logger.debug("Waiting for completion of filtering processes")
        self.mea_input_queue.put(None)
        filtering_process.join()
        self.__get_from_queue_into_list(queue, results)
        if not self.mea_input_queue.empty():
            resources = self.mea_input_queue.get()
            mea_cpu = resources.get(TAG_CPU_TIME, 0.0)
            mea_memory = resources.get(TAG_MEMORY_USAGE, 0)
            mea_wall = resources.get(TAG_WALL_TIME, 0.0)
        else:
            mea_memory = 0
            mea_cpu = 0.0
            mea_wall = 0.0
            self.logger.warning("MEA resources were not obtained")

        overall_cpu_time = time.process_time() - self.start_cpu_time
        overall_wall_time = time.time() - self.start_time
        self.logger.debug("Overall wall time of script: {}".format(overall_wall_time))
        self.logger.debug("Overall CPU time of script: {}".format(overall_cpu_time))
        self.logger.info("Solving of verification tasks has been completed")

        reports_prefix = self.__get_result_file_prefix()
        report_launches = os.path.join(results_dir, "report_launches_{0}.csv".format(reports_prefix))
        result_archive = os.path.join(results_dir, "results_{0}.zip".format(reports_prefix))

        self.logger.debug("Processing results")
        cov_lines = {}
        cov_funcs = {}
        stats_by_rules = {}
        cov_cpu = 0
        wall_cov = 0
        cov_mem_array = list()
        for rule in rules:
            if rule == RULE_COVERAGE:
                continue
            stats_by_rules[rule] = GlobalStatistics()
        for result in results:
            if result.rule == RULE_COVERAGE:
                key = self.__get_none_rule_key(result)
                cov_lines[key] = result.cov_lines
                cov_funcs[key] = result.cov_funcs
            else:
                if result.rule in DEADLOCK_SUB_PROPERTIES:
                    rule = RULE_DEADLOCK
                else:
                    rule = result.rule
                stats_by_rules[rule].add_result(result)
                if result.filtering_cpu:
                    mea_cpu += result.filtering_cpu
                cov_cpu += result.coverage_resources.get(TAG_CPU_TIME, 0)
                wall_cov += result.coverage_resources.get(TAG_WALL_TIME, 0)
                cov_mem_array.append(result.coverage_resources.get(TAG_MEMORY_USAGE, 0))
        if cov_mem_array:
            cov_mem = sum(cov_mem_array)/len(cov_mem_array)
        else:
            cov_mem = 0

        # Yes, this is a rough approximation, but nothing better is available.
        if self.scheduler == SCHEDULER_CLOUD:
            wall_cov /= self.cpu_cores
        else:
            wall_cov /= min(number_of_processes, self.cpu_cores)

        self.logger.info("Preparing report on launches into file: '{}'".format(report_launches))
        with open(report_launches, "w") as f_report:
            f_report.write("Subsystem;Rule;Entrypoint;Verdict;Termination;CPU;Wall;Memory;Relevancy;"
                           "Traces;Filtered traces;Work dir;Cov lines;Cov funcs;MEA time\n")  # Header.
            for result in results:
                # Add coverage information.
                if result.verdict == VERDICT_SAFE and not result.rule == RULE_COVERAGE:
                    key = self.__get_none_rule_key(result)
                    if not result.cov_lines:
                        result.cov_lines = cov_lines.get(key, 0.0)
                    if not result.cov_funcs:
                        result.cov_funcs = cov_funcs.get(key, 0.0)
                f_report.write(str(result) + "\n")

        report_components = os.path.join(results_dir, "report_components_{0}.csv".format(reports_prefix))
        self.logger.info("Preparing report on components into file: '{}'".format(report_components))
        with open(report_components, "w") as f_report:
            f_report.write("Name;CPU;Wall;Memory\n")  # Header.
            f_report.write("{0};{1};{2};{3}\n".format(COMPONENT_PREPARATOR, round(preparation_cpu_time, ROUND_DIGITS),
                                                      round(preparation_wall_time, ROUND_DIGITS),
                                                      preparation_memory_usage))
            f_report.write("{0};{1};{2};{3}\n".format(COMPONENT_LAUNCHER, round(overall_cpu_time, ROUND_DIGITS),
                                                      round(overall_wall_time, ROUND_DIGITS),
                                                      int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024))
            f_report.write("{0};{1};{2};{3}\n".format(COMPONENT_MEA, round(mea_cpu, ROUND_DIGITS),
                                                      round(mea_wall, ROUND_DIGITS), mea_memory))
            f_report.write("{0};{1};{2};{3}\n".format(COMPONENT_COVERAGE, round(cov_cpu, ROUND_DIGITS),
                                                      round(wall_cov, ROUND_DIGITS), cov_mem))
            if qualifier_resources:
                f_report.write("{0};{1};{2};{3}\n".format(COMPONENT_QUALIFIER,
                                                          round(qualifier_resources[TAG_CPU_TIME], ROUND_DIGITS),
                                                          round(qualifier_resources[TAG_WALL_TIME], ROUND_DIGITS),
                                                          round(qualifier_resources[TAG_MEMORY_USAGE], ROUND_DIGITS)))
            if builder_resources:
                f_report.write("{0};{1};{2};{3}\n".format(COMPONENT_BUILDER,
                                                          round(builder_resources[TAG_CPU_TIME], ROUND_DIGITS),
                                                          round(builder_resources[TAG_WALL_TIME], ROUND_DIGITS),
                                                          round(builder_resources[TAG_MEMORY_USAGE], ROUND_DIGITS)))

        short_report = os.path.join(results_dir, "short_report_{0}.csv".format(reports_prefix))
        self.logger.info("Preparing short report into file: '{}'".format(short_report))
        with open(short_report, "w") as f_report:
            f_report.write("Rule;Safes;Unsafes;Unknowns;Relevant;Traces;Filtered;CPU;Wall;Mem\n")
            overall_stats = GlobalStatistics()
            for rule, info in sorted(stats_by_rules.items()):
                info.sum_memory()
                f_report.write("{0};{1}\n".format(rule, info))
                overall_stats.sum(info)
            f_report.write("Overall;{0}\n".format(overall_stats))

        self.logger.info("Exporting results into archive: '{}'".format(result_archive))

        exporter = Exporter(self.config, DEFAULT_EXPORT_DIR, self.install_dir)
        exporter.export_traces(report_launches, report_components, result_archive,
                               {COMPONENT_PREPARATOR: preparator_unknowns})

        uploader_config = self.config.get(UPLOADER, {})
        if uploader_config and uploader_config.get(TAG_UPLOADER_UPLOAD_RESULTS, False):
            self.__upload_results(uploader_config, result_archive)

        if not self.debug:
            self.logger.info("Cleaning working directories")
            for mode, path in DEFAULT_CPACHECKER_CLOUD.items():
                cpa_path = self.get_tool_path(path)
                shutil.rmtree(os.path.join(cpa_path, DEFAULT_CIL_DIR), ignore_errors=True)
                shutil.rmtree(os.path.join(cpa_path, VERIFIER_PROPERTIES_DIR), ignore_errors=True)
            shutil.rmtree(DEFAULT_MAIN_DIR, ignore_errors=True)
            shutil.rmtree(DEFAULT_EXPORT_DIR, ignore_errors=True)
            if self.backup and os.path.exists(self.backup):
                os.remove(self.backup)
            shutil.rmtree(DEFAULT_LAUNCHES_DIR, ignore_errors=True)
        self.logger.info("Finishing verification of '{}' configuration".format(self.config_file))
        os.chdir(self.root_dir)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", help="list of config files", required=True, nargs="+")
    options = parser.parse_args()
    for config in options.config:
        launcher = Launcher(config)
        launcher.launch()
        del launcher
