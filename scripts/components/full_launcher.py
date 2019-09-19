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

import resource
from collections import deque
from time import sleep
from xml.dom import minidom

from components.builder import Builder
from components.exporter import Exporter
from components.launcher import *
from components.main_generator import MainGenerator
from components.preparator import Preparator
from components.qualifier import Qualifier
from models.verification_result import *


class FullLauncher(Launcher):
    """
    Main component, which creates verification tasks for the given system, launches them and processes results.
    """
    def __init__(self, config_file):
        super(FullLauncher, self).__init__(COMPONENT_LAUNCHER, config_file)

        self.entrypoints_dir = os.path.join(self.root_dir, DEFAULT_ENTRYPOINTS_DIR)
        self.rules_dir = os.path.join(self.root_dir, DEFAULT_RULES_DIR)
        self.options_dir = os.path.join(self.root_dir, VERIFIER_FILES_DIR, VERIFIER_OPTIONS_DIR)
        self.patches_dir = os.path.join(self.root_dir, DEFAULT_SOURCE_PATCHES_DIR)
        self.plugin_dir = os.path.join(self.root_dir, DEFAULT_PLUGIN_DIR)

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
        resource_queue_filter.put({TAG_MEMORY_USAGE: result.mea_resources.get(TAG_MEMORY_USAGE, 0),
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
            fp.write(minidom.parseString(ElementTree.tostring(benchmark)).toprettyxml(indent="\t"))

        return launch_directory, benchmark_name

    def __process_single_launch_results(self, result, launch_directory, queue):
        result.parse_output_dir(launch_directory, self.install_dir, self.result_dir_et)
        self._process_coverage(result, launch_directory, self.build_results.keys())
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

        self.__process_single_launch_results(result, launch_directory, queue)

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

                if commits and commits[0]:
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
            fp.write(minidom.parseString(ElementTree.tostring(benchmark_cur)).toprettyxml(indent="\t"))

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
                                                  launch.rule, os.path.basename(launch.cil_file)))) +\
                    glob.glob(os.path.join(group_directory, "*.files", "{0}_{2}_{1}.{3}*".
                                   format(launch.entrypoint, os.path.basename(launch.cil_file),
                                          launch.rule, os.path.basename(launch.cil_file)), 'output'))

            launch_dir = self._copy_result_files(files, group_directory)
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
                                                              args=(result, launch_dir, queue))
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

        self.logger.debug("Check resource limitations")
        max_cores = multiprocessing.cpu_count()
        self.cpu_cores = max_cores
        self.logger.debug("Machine has {} CPU cores".format(max_cores))
        max_memory = int(int(subprocess.check_output("free -m", shell=True).splitlines()[1].split()[1]) / 1000)
        self.logger.debug("Machine has {}GB of RAM".format(max_memory))

        if self.component_config.get(TAG_BACKUP_WRITE, False):
            self.backup = "{0}{1}.csv".format(DEFAULT_BACKUP_PREFIX, self._get_result_file_prefix())

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

        find_coverage = self.config.get(COMPONENT_COVERAGE, {}).get(TAG_MAX_COVERAGE, False)
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

        rules = sorted(set(rules))
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
        component_attrs = {COMPONENT_PREPARATOR: dict()}
        build_commands = dict()
        while not resource_queue.empty():
            prep_data = resource_queue.get()
            preparator_wall_time = prep_data.get(TAG_WALL_TIME, 0.0)
            preparator_cpu_time = prep_data.get(TAG_CPU_TIME, 0.0)
            preparator_memory = prep_data.get(TAG_MEMORY_USAGE, 0)
            preparation_memory_usage_all.append(preparator_memory)
            preparation_cpu_time += preparator_cpu_time
            if TAG_LOG_FILE in prep_data:
                cil_file = prep_data.get(TAG_CIL_FILE, "")
                attrs = list()
                if cil_file:
                    res = re.search(r"(\w+)_([^_]+)_(\w+)\.i", os.path.basename(cil_file))
                    if res:
                        attrs = [
                            {"name": "Subsystem", "value": res.group(1)},
                            {"name": "Rule specification", "value": res.group(2)},
                            {"name": "Strategy", "value": res.group(3)},
                        ]

                for log in prep_data.get(TAG_LOG_FILE):
                    preparator_unknowns.append({
                        TAG_LOG_FILE: log,
                        TAG_CPU_TIME: round(preparator_cpu_time * 1000),
                        TAG_WALL_TIME: round(preparator_wall_time * 1000),
                        TAG_MEMORY_USAGE: preparator_memory,
                        TAG_ATTRS: attrs
                    })
            if TAG_PREP_RESULTS in prep_data:
                with open(prep_data[TAG_PREP_RESULTS]) as fd:
                    data = json.load(fd)
                    for cmd, args in data.items():
                        if cmd not in build_commands:
                            build_commands[cmd] = args
                        else:
                            for i in range(0, len(args)):
                                build_commands[cmd][i] = build_commands[cmd][i] or args[i]

        if build_commands:
            overall_build_commands = len(build_commands)
            potential_build_commands = 0
            filtered_build_commands = 0
            compiled_build_commands = 0
            processed_build_commands = 0
            for cmd, args in build_commands.items():
                if args[0]:
                    potential_build_commands += 1
                if args[1]:
                    filtered_build_commands += 1
                if args[2]:
                    compiled_build_commands += 1
                if args[3]:
                    processed_build_commands += 1
            component_attrs[COMPONENT_PREPARATOR] = [
                {
                    "name": "Build commands", "value": [
                        {"name": "overall", "value": str(overall_build_commands)},
                        {"name": "potential", "value": str(potential_build_commands)},
                        {"name": "filtered", "value": str(filtered_build_commands)},
                        {"name": "compiled", "value": str(compiled_build_commands)},
                        {"name": "processed", "value": str(processed_build_commands)}
                    ]
                }
            ]
            self.logger.info("Number of build commands: {}; potentially can be used (not ignored): {}; "
                              "filtered for checked subsystems: {}; compiled: {}; processed: {}".format(
                overall_build_commands, potential_build_commands, filtered_build_commands, compiled_build_commands,
                processed_build_commands
            ))
            # TODO: upload those unused build commands for common coverage data

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
        if number_of_launches == 0:
            sys.exit("No launches were set by the given configuration")
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
                self._get_from_queue_into_list(queue, results)
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
                            self._get_from_queue_into_list(queue, results)
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
                self._get_from_queue_into_list(queue, results)
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
        self._get_from_queue_into_list(queue, results)
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

        report_launches, result_archive, report_components, short_report, report_resources = self._get_results_names()

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
                key = self._get_none_rule_key(result)
                cov_lines[key] = result.cov_lines
                cov_funcs[key] = result.cov_funcs
            else:
                if result.rule in DEADLOCK_SUB_PROPERTIES:
                    rule = RULE_DEADLOCK
                else:
                    rule = result.rule
                stats_by_rules[rule].add_result(result)
                mea_cpu += result.mea_resources.get(TAG_CPU_TIME, 0.0)
                cov_cpu += result.coverage_resources.get(TAG_CPU_TIME, 0)
                wall_cov += result.coverage_resources.get(TAG_WALL_TIME, 0)
                cov_mem_array.append(result.coverage_resources.get(TAG_MEMORY_USAGE, 0))
        if cov_mem_array:
            cov_mem = max(cov_mem_array)
        else:
            cov_mem = 0

        # Yes, this is a rough approximation, but nothing better is available.
        if self.scheduler == SCHEDULER_CLOUD:
            wall_cov /= self.cpu_cores
        else:
            wall_cov /= min(number_of_processes, self.cpu_cores)

        self._print_launches_report(report_launches, report_resources, results, cov_lines, cov_funcs)
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

        config = {
            TAG_CONFIG_MEMORY_LIMIT: str(memory_limit) + "GB",
            TAG_CONFIG_CPU_TIME_LIMIT: time_limit,
            TAG_CONFIG_CPU_CORES_LIMIT: core_limit
        }
        exporter = Exporter(self.config, DEFAULT_EXPORT_DIR, self.install_dir)
        exporter.export(report_launches, report_resources, report_components, result_archive,
                        unknown_desc={COMPONENT_PREPARATOR: preparator_unknowns}, component_attrs=component_attrs,
                        verifier_config=config)

        uploader_config = self.config.get(UPLOADER, {})
        if uploader_config and uploader_config.get(TAG_UPLOADER_UPLOAD_RESULTS, False):
            self._upload_results(uploader_config, result_archive)

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
            shutil.rmtree(DEFAULT_PREPROCESS_DIR, ignore_errors=True)
        self.logger.info("Finishing verification of '{}' configuration".format(self.config_file))
        os.chdir(self.root_dir)
