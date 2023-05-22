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
# pylint: disable=attribute-defined-outside-init, too-many-lines

"""
Main component for CV benchmark launches.
"""

import resource
from collections import deque
from time import sleep
from xml.dom import minidom

from aux.common import *
from components.builder import Builder
from components.exporter import Exporter
from components.launcher import *
from components.main_generator import MainGenerator
from components.preparator import Preparator
from components.qualifier import Qualifier
from models.verification_result import *


class FullLauncher(Launcher):
    """
    Main component, which creates verification tasks for the given system,
    launches them and processes results.
    """

    def __init__(self, config_file):
        super().__init__(COMPONENT_LAUNCHER, config_file)

        if not self.scheduler or self.scheduler not in SCHEDULERS:
            sys.exit(f"Scheduler '{self.scheduler}' is not known. Choose from {SCHEDULERS}")

        self.entrypoints_dir = os.path.join(self.root_dir, DEFAULT_ENTRYPOINTS_DIR)
        self.models_dir = os.path.join(self.root_dir, DEFAULT_PROPERTIES_DIR, DEFAULT_MODELS_DIR)
        self.patches_dir = os.path.join(self.root_dir, DEFAULT_SOURCE_PATCHES_DIR)
        self.plugin_dir = os.path.join(self.root_dir, DEFAULT_PLUGIN_DIR)

        # Id to separate internal files (verifier configs, patches, etc.).
        self.system_id = self.config.get(TAG_SYSTEM_ID, "")

        # Map of verifier modes to files with specific options.
        self.verifier_options = {}

        # Properties description.
        plugin_properties_desc_file = self.__get_file_for_system(DEFAULT_PROPERTIES_DIR,
                                                                 DEFAULT_PROPERTIES_DESC_FILE)
        self.properties_desc = PropertiesDescription(plugin_properties_desc_file)
        self.is_cgroup_v2 = "cgroup2" in self.command_caller_with_output(
            "mount | grep '^cgroup' | awk '{print $1}' | uniq")
        self.mea_input_queue = multiprocessing.Queue()
        self.build_results = None

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
        self.logger.debug(f"Starting scheduler for filtering with {number_of_processes} processes")
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
                        self.logger.info(
                            f"Scheduling new filtering process: subsystem '{result.id}', "
                            f"rule '{result.rule}', entrypoint '{result.entrypoint}'")
                        process_pool[i] = multiprocessing.Process(
                            target=self.__perform_filtering, name=f"MEA_{i}",
                            args=(result, output_queue, resource_queue_filter))
                        if self.debug:
                            load = 0
                            for process in process_pool:
                                if process:
                                    load += 1
                            self.logger.debug(f"Scheduler for filtering load is "
                                              f"{round(100 * load / number_of_processes, 2)}%")

                        process_pool[i].start()
                sleep(BUSY_WAITING_INTERVAL * 10)
                self.__count_filter_resources(resource_queue_filter)
        except NestedLoop:
            wait_for_launches(process_pool)
            self.__count_filter_resources(resource_queue_filter)
        except Exception as exception:
            self.logger.error(f"Process for filtering results was terminated: {exception}",
                              exc_info=True)
            kill_launches(process_pool)
        self.logger.info("Stopping filtering scheduler")
        cpu_time = time.process_time() - cpu_start
        self.logger.debug(f"Filtering took {cpu_time} seconds of overheads")
        scheduler_memory_usage = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
        # There is main thread and children processes.
        self.mea_memory_usage += scheduler_memory_usage
        self.logger.debug(f"Filtering maximum memory usage: {self.mea_memory_usage}B")
        self.mea_input_queue.put({TAG_MEMORY_USAGE: self.mea_memory_usage,
                                  TAG_CPU_TIME: cpu_time,
                                  TAG_WALL_TIME: self.mea_wall_time})
        sys.exit(0)

    def __create_benchmark(self, launch: VerificationTask, benchmark):
        # Create temp launch directory.
        launch_directory = os.path.abspath(tempfile.mkdtemp(dir=DEFAULT_LAUNCHES_DIR))

        # Add specific options.
        self.__resolve_property_file(benchmark, launch)
        ElementTree.SubElement(benchmark.find("rundefinition"), "option", {"name": "-setprop"}). \
            text = f"output.path={launch_directory}"
        ElementTree.SubElement(benchmark.find("rundefinition"), "option",
                               {"name": "-entryfunction"}).text = launch.entrypoint
        ElementTree.SubElement(ElementTree.SubElement(benchmark, "tasks"), "include").text = \
            launch.cil_file
        if not launch.entry_desc.optimize:
            for option in VERIFIER_OPTIONS_NOT_OPTIMIZED:
                ElementTree.SubElement(benchmark.find("rundefinition"), "option",
                                       {"name": "-setprop"}).text = option

        # Create benchmark file.
        benchmark_name = f"{DEFAULT_LAUNCHES_DIR}/benchmark_" \
                         f"{os.path.basename(launch_directory)}.xml"
        with open(benchmark_name, "w", encoding="ascii") as file_obj:
            file_obj.write(minidom.parseString(ElementTree.tostring(benchmark)).
                           toprettyxml(indent="\t"))

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

        # If output directory is hardcoded in a verifier, then we need to move it.
        is_move_output_dir = self.properties_desc.get_property_arg(result.rule,
                                                                   PROPERTY_IS_MOVE_OUTPUT)
        cur_cwd = os.getcwd()
        if is_move_output_dir:
            shutil.move(benchmark_name, launch_directory)
            benchmark_name = os.path.basename(benchmark_name)
            os.chdir(launch_directory)

        # Verifier launch.
        subprocess.check_call(f"benchexec --no-compress-results --container --full-access-dir / -o "
                              f"{launch_directory} {benchmark_name} {self.benchmark_args}",
                              shell=True, stderr=self.output_desc, stdout=self.output_desc)

        # Make output directory similar to the other properties.
        if is_move_output_dir:
            if os.path.exists(HARDCODED_RACES_OUTPUT_DIR):
                for file in glob.glob(f"{HARDCODED_RACES_OUTPUT_DIR}/witness*"):
                    shutil.move(file, launch_directory)
                os.rmdir(HARDCODED_RACES_OUTPUT_DIR)
            if not self.debug:
                os.remove(benchmark_name)
            os.chdir(cur_cwd)
        else:
            if not self.debug:
                os.remove(benchmark_name)

        self.__process_single_launch_results(result, launch_directory, queue)

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
        # Information, that will be used by Preparator (source directories and build commands).
        build_results = {}
        cur_dir = os.getcwd()

        self.logger.info("Preparing source directories")
        sources = self.config.get(COMPONENT_BUILDER, {}).get(TAG_SOURCES, [])
        commits = self.config.get(TAG_COMMITS, None)

        if not sources:
            sys.exit("Sources to be verified were not specified")

        builders = {}
        for sources_config in sources:
            identifier = sources_config.get(TAG_ID)
            source_dir = os.path.abspath(sources_config.get(TAG_SOURCE_DIR))
            branch = sources_config.get(TAG_BRANCH, None)
            build_patch = sources_config.get(TAG_BUILD_PATCH, None)
            skip = sources_config.get(TAG_SKIP, False)
            build_config = sources_config.get(TAG_BUILD_CONFIG, {})
            cached_commands = sources_config.get(TAG_CACHED_COMMANDS, None)
            repository = sources_config.get(TAG_REPOSITORY, None)
            id_str = re.sub('\\W', '_', identifier)
            build_commands = os.path.join(cur_dir, f"cmds_{id_str}.json")

            if not source_dir or not os.path.exists(source_dir):
                sys.exit(f"Source directory '{source_dir}' does not exist")

            if build_config:
                build_results[source_dir] = build_commands

            if skip:
                self.logger.debug(
                    f"Skipping building of sources '{identifier}' (directory {source_dir})")
                if build_config:
                    if not (cached_commands and os.path.exists(cached_commands)):
                        sys.exit(f"Cached build commands were not specified for sources "
                                 f"'{identifier}', preparation of which was skipped")
                    shutil.copy(cached_commands, build_commands)
                continue
            self.logger.debug(f"Building of sources '{identifier}' (directory {source_dir})")

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
                    self.logger.debug(f"Taking build commands from cached file {cached_commands}")
                    shutil.copy(cached_commands, build_commands)
                else:
                    self.logger.debug(f"Generating build commands in file {build_commands}")
                    builders[builder] = build_commands

        for sources_config in sources:
            source_dir = os.path.abspath(sources_config.get(TAG_SOURCE_DIR))
            patches = sources_config.get(TAG_PATCH, [])

            builder = None
            for tmp_builder, _ in builders.items():
                if tmp_builder.source_dir == source_dir:
                    builder = tmp_builder
                    break

            if builder:
                build_commands = builders[builder]
                if build_commands:
                    builder.build(build_commands)
                builder_resources = self.add_resources(builder.get_component_full_stats(),
                                                       builder_resources)

                if commits and commits[0]:
                    if not builder.repository:
                        sys.exit("Cannot check commits without repository")
                    self.logger.debug(f"Finding all entrypoints for specified commits {commits}")
                    qualifier = Qualifier(builder, self.__get_files_for_system(
                        self.entrypoints_dir, "*" + JSON_EXTENSION))
                    specific_sources_new, specific_functions_new = \
                        qualifier.analyse_commits(commits)
                    specific_functions_new = qualifier.find_functions(specific_functions_new)
                    specific_sources = specific_sources.union(specific_sources_new)
                    specific_functions = specific_functions.union(specific_functions_new)
                    qualifier_resources = self.add_resources(qualifier.stop(), qualifier_resources)

                if patches:
                    for patch in patches:
                        self.logger.debug(f"Apply patch {patch}")
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

    def __resolve_property_file(self, rundefinition: ElementTree.Element,
                                launch: VerificationTask) -> None:
        """
        Property file is resolved in the following way:
         - rule specific automaton (*.spc file);
        Note, that any manually specified property files in options file will be added as well.
        :param rundefinition: definition of a single run in BenchExec format;
        :param launch: verification task to be checked;
        """
        # TODO: support several properties here
        # Use specified automaton file.
        automaton_file = self.properties_desc.get_property_arg(launch.rule,
                                                               PROPERTY_SPECIFICATION_AUTOMATON)
        if automaton_file:
            automaton_file = self.__get_file_for_system(
                os.path.join(self.root_dir, DEFAULT_PROPERTIES_DIR, DEFAULT_AUTOMATA_DIR),
                automaton_file)
        else:
            # Use default automaton file.
            automaton_file = self.__get_file_for_system(
                os.path.join(self.root_dir, DEFAULT_PROPERTIES_DIR, DEFAULT_AUTOMATA_DIR),
                launch.rule + ".spc")
        if os.path.exists(automaton_file):
            automaton_file = os.path.join(DEFAULT_AUTOMATA_DIR, os.path.basename(automaton_file))
            ElementTree.SubElement(rundefinition, "option", {"name": "-spec"}).text = automaton_file

    def __parse_verifier_options(self, prop: str, rundefinition: ElementTree.Element) -> None:
        parsed_options = {}

        def parse_options(content: dict):
            for name, values in content.items():
                if values:
                    for value in values:
                        if name == "-config":
                            potential_abs_path = os.path.join(self.install_dir,
                                                              self.__get_mode(prop), value)
                            if os.path.exists(potential_abs_path):
                                value = potential_abs_path
                        if name == "-setprop":
                            (parsed_key, parsed_val) = str(value).split("=")
                            parsed_options[parsed_key] = parsed_val
                        else:
                            ElementTree.SubElement(rundefinition, "option", {"name": name}).text = \
                                value
                else:
                    ElementTree.SubElement(rundefinition, "option", {"name": name})

        common_options = self.properties_desc.get_property_arg(PROPERTY_COMMON, PROPERTY_OPTIONS)
        specific_options = self.properties_desc.get_property_arg(prop, PROPERTY_OPTIONS)

        parse_options(common_options)
        parse_options(specific_options)
        for key, val in parsed_options.items():
            ElementTree.SubElement(rundefinition, "option", {"name": "-setprop"}).text \
                = f"{key}={val}"

    def __process_single_group(self, mode, launches, time_limit, memory_limit, core_limit,
                               heap_limit, internal_time_limit, queue):
        # TODO: This is for vcloud only - not supported!
        # Prepare benchmark file for the whole group.
        benchmark_cur = self.__create_benchmark_config(time_limit, core_limit, memory_limit)
        ElementTree.SubElement(benchmark_cur, "resultfiles").text = "**/*"
        ElementTree.SubElement(benchmark_cur, "requiredfiles").text = "properties/*"
        for launch in launches:
            name = f"{launch.entrypoint}_{launch.rule}_{os.path.basename(launch.cil_file)}"
            rundefinition = ElementTree.SubElement(benchmark_cur, "rundefinition", {"name": name})
            ElementTree.SubElement(rundefinition, "option", {"name": "-heap"}).text = \
                f"{heap_limit}m"
            ElementTree.SubElement(rundefinition, "option", {"name": "-timelimit"}).text = str(
                internal_time_limit)
            self.__resolve_property_file(rundefinition, launch)
            self.__parse_verifier_options(launch.rule, rundefinition)
            ElementTree.SubElement(rundefinition, "option", {"name": "-entryfunction"}).text = \
                launch.entrypoint
            if not launch.entry_desc.optimize:
                for option in VERIFIER_OPTIONS_NOT_OPTIMIZED:
                    ElementTree.SubElement(rundefinition, "option", {"name": "-setprop"}).text = \
                        option
            ElementTree.SubElement(ElementTree.SubElement(rundefinition, "tasks"),
                                   "include").text = os.path.relpath(launch.cil_file)
        benchmark_name = f"{DEFAULT_LAUNCHES_DIR}/benchmark_{mode}.xml"
        with open(benchmark_name, "w", encoding="ascii") as file_obj:
            file_obj.write(minidom.parseString(ElementTree.tostring(benchmark_cur)).toprettyxml(
                indent="\t"))

        # Create temp directory for group.
        group_directory = os.path.abspath(tempfile.mkdtemp(dir=DEFAULT_LAUNCHES_DIR))

        # Creating links.
        cil_abs_dir = os.path.join(os.getcwd(), DEFAULT_CIL_DIR)
        properties_abs_dir = os.path.join(self.work_dir, DEFAULT_AUTOMATA_DIR)
        benchmark_abs_dir = os.path.abspath(benchmark_name)
        cil_rel_dir = DEFAULT_CIL_DIR
        properties_rel_dir = DEFAULT_AUTOMATA_DIR
        benchmark_rel_dir = os.path.basename(benchmark_name)

        # Launch from CPAchecker directory
        verifier_dir = os.path.join(self.install_dir, mode)
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
        with open(log_file_name, 'w', encoding="utf8") as f_log:
            # Launch group.
            command = f"python3 scripts/benchmark.py --no-compress-results -o " \
                      f"{group_directory} --container {os.path.basename(benchmark_name)} " \
                      f"{self.benchmark_args}"
            self.logger.debug(f"Launching benchmark: {command}")
            subprocess.check_call(command, shell=True, stderr=f_log, stdout=f_log)

        # Process results (in parallel -- we assume, that the master host is free).
        process_pool = []
        for i in range(self.cpu_cores):
            process_pool.append(None)
        for launch in launches:
            benchexec_id_regexp = f"{launch.entrypoint}_{launch.rule}_" \
                                  f"{os.path.basename(launch.cil_file)}." \
                                  f"{os.path.basename(launch.cil_file)}*"
            files = glob.glob(os.path.join(group_directory, "*.logfiles", benchexec_id_regexp)) + \
                glob.glob(os.path.join(group_directory, "*.files", benchexec_id_regexp, 'output'))

            launch_dir = self._copy_result_files(files, group_directory)
            xml_file_regexp = f'benchmark*results.{launch.entrypoint}_{launch.rule}_' \
                              f'{os.path.basename(launch.cil_file)}.xml'
            xml_files = glob.glob(os.path.join(group_directory, xml_file_regexp))
            if not xml_files:
                self.logger.warning(f"There is no xml file for launch {launch}")
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
                            process_pool[i] = multiprocessing.Process(
                                target=self.__process_single_launch_results, name=result.entrypoint,
                                args=(result, launch_dir, queue))
                            process_pool[i].start()
                            raise NestedLoop
                    sleep(BUSY_WAITING_INTERVAL)
            except NestedLoop:
                pass
            except Exception as exception:
                self.logger.error(f"Error during processing results: {exception}", exc_info=True)
                kill_launches(process_pool)
        wait_for_launches(process_pool)
        os.chdir(cur_dir)

    def __get_groups_with_established_connections(self):
        result = set()
        log_files = glob.glob(os.path.join(self.work_dir, DEFAULT_LAUNCHES_DIR, "*",
                                           CLOUD_BENCHMARK_LOG))
        for log_file in log_files:
            if os.path.exists(log_file):
                with open(log_file, errors='ignore', encoding="utf8") as f_log:
                    for line in f_log.readlines():
                        res = re.search(r'INFO	BenchmarkClient:OutputHandler\$1\.onSuccess	'
                                        r'Received run result for run 1 of', line)
                        if res:
                            group_id = os.path.basename(os.path.dirname(log_file))
                            result.add(group_id)
                            break
        return result

    def __get_file_for_system(self, prefix: str, file: str) -> str:
        if not file:
            return ""
        plugin_dir = os.path.join(self.plugin_dir, self.system_id, os.path.relpath(prefix,
                                                                                   self.root_dir))
        if self.system_id:
            new_path = os.path.join(plugin_dir, file)
            if os.path.exists(new_path):
                return new_path
        new_path = os.path.join(prefix, file)
        if os.path.exists(new_path):
            return new_path
        return ""

    def __get_files_for_system(self, prefix: str, pattern: str) -> list:
        plugin_dir = os.path.join(self.plugin_dir, self.system_id, os.path.relpath(prefix,
                                                                                   self.root_dir))
        if self.system_id:
            result = glob.glob(os.path.join(plugin_dir, pattern))
            if result:
                return result
        result = glob.glob(os.path.join(prefix, pattern))
        if result:
            return result
        self.logger.debug(f"Cannot find any files by pattern {pattern} neither in basic "
                          f"directory {prefix} nor in plugin directory {plugin_dir}")
        return []

    def __get_mode(self, prop: str) -> str:
        return self.properties_desc.get_property_arg(prop, PROPERTY_MODE)

    def __create_benchmark_config(self, time_limit, core_limit, memory_limit):
        base_config = {
            "tool": CPACHECKER,
        }
        if time_limit > 0:
            base_config["timelimit"] = str(time_limit)
        if core_limit > 0:
            base_config["cpuCores"] = str(core_limit)
        if not self.is_cgroup_v2:
            base_config["memlimit"] = str(memory_limit) + "GB"
        return ElementTree.Element("benchmark", base_config)

    def launch(self):
        """
        Main method
        """

        # Process common directories.

        results = []  # Verification results.
        backup_read = self.component_config.get(TAG_BACKUP_READ, False)
        self.logger.debug(f"Clearing old working directory '{self.work_dir}'")
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
            shutil.rmtree(DEFAULT_AUTOMATA_DIR, ignore_errors=True)
        os.makedirs(DEFAULT_AUTOMATA_DIR, exist_ok=True)
        os.makedirs(DEFAULT_CIL_DIR, exist_ok=True)
        os.makedirs(DEFAULT_MAIN_DIR, exist_ok=True)
        os.makedirs(DEFAULT_LAUNCHES_DIR, exist_ok=True)
        os.makedirs(DEFAULT_PREPROCESS_DIR, exist_ok=True)
        os.makedirs(DEFAULT_EXPORT_DIR, exist_ok=True)

        self.logger.debug("Check resource limitations")
        max_cores = multiprocessing.cpu_count()
        self.cpu_cores = max_cores
        self.logger.debug(f"Machine has {max_cores} CPU cores")
        max_memory = int(int(subprocess.check_output("free -m", shell=True).
                             splitlines()[1].split()[1]) / 1000)
        self.logger.debug(f"Machine has {max_memory}GB of RAM")

        if self.component_config.get(TAG_BACKUP_WRITE, False):
            self.backup = f"{DEFAULT_BACKUP_PREFIX}{self._get_result_file_prefix()}.csv"

        resource_limits = self.component_config.get(TAG_RESOURCE_LIMITATIONS)
        memory_limit = resource_limits.get(TAG_LIMIT_MEMORY, max_memory)
        if not self.scheduler == SCHEDULER_CLOUD and max_memory < memory_limit:
            sys.exit(f"There is not enough memory to start scheduler: {memory_limit}GB are "
                     f"required, whereas only {max_memory}GB are available.")
        # Basic conversion to get Java heap size (in MB)
        heap_limit = int(memory_limit * 1000 * 13 / 15)

        time_limit = resource_limits[TAG_LIMIT_CPU_TIME]

        statistics_time = self.component_config.get(TAG_STATISTICS_TIME,
                                                    DEFAULT_TIME_FOR_STATISTICS)
        if statistics_time >= time_limit:
            self.logger.warning(f"Specified time for printing statistics {statistics_time}s is "
                                f"bigger than overall time limit. Ignoring statistics time")
            statistics_time = 0
        internal_time_limit = time_limit - statistics_time

        core_limit = resource_limits.get(TAG_LIMIT_CPU_CORES, max_cores)
        if not self.scheduler == SCHEDULER_CLOUD and max_cores < core_limit:
            sys.exit(f"There is not enough CPU cores to start scheduler: {core_limit} "
                     f"are required, whereas only {max_cores} are available.")

        specific_functions = set(self.config.get(TAG_CALLERS, set()))
        specific_sources = set()
        qualifier_resources = {}
        builder_resources = {}
        if self.config.get(TAG_COMMITS) and specific_functions:
            sys.exit(
                "Sanity check failed: it is forbidden to specify both callers and commits tags")

        if memory_limit > 0:
            proc_by_memory = int(max_memory / memory_limit)
        else:
            proc_by_memory = max_memory
        if core_limit > 0:
            proc_by_cores = int(max_cores / core_limit)
        else:
            proc_by_cores = max_cores
        parallel_launches = int(self.component_config.get(TAG_PARALLEL_LAUNCHES, 0))
        if parallel_launches < 0:
            sys.exit(f"Incorrect value for number of parallel launches: {parallel_launches}")
        if not parallel_launches:
            number_of_processes = min(proc_by_memory, proc_by_cores)
        else:
            # Careful with this number: if it is too big, memory may be exhausted.
            number_of_processes = parallel_launches
        self.logger.debug(f"Max parallel verifier launches on current host: {number_of_processes}")
        self.logger.debug(f"Each verifier launch will be limited to {memory_limit}GB of RAM, "
                          f"{time_limit} seconds of CPU time and {core_limit} CPU cores")

        # We need to perform sanity checks before complex operation of building.
        rules = self.config.get("properties")
        if not rules:
            sys.exit("No properties to be checked were specified")

        ep_desc_files = self.config.get(TAG_ENTRYPOINTS_DESC)
        entrypoints_desc = set()
        if not ep_desc_files:
            sys.exit("No file with description of entry points to be checked were specified")
        else:
            for group in ep_desc_files:
                self.logger.debug(f"Processing given group of files: {group}")
                files = []
                if isinstance(group, list):
                    for elem in group:
                        files.extend(self.__get_files_for_system(self.entrypoints_dir,
                                                                 elem + JSON_EXTENSION))
                    identifier = "_".join(group)
                    self.logger.debug(f"Processing joint files with entry point description "
                                      f"'{identifier}'")
                    entrypoints_desc.add(EntryPointDesc(files, identifier))
                else:
                    # Wildcards are supported here.
                    files = self.__get_files_for_system(self.entrypoints_dir,
                                                        group + JSON_EXTENSION)
                    for file in files:
                        self.logger.debug(f"Processing file with entry point description '{file}'")
                        identifier = os.path.basename(file)[:-len(JSON_EXTENSION)]
                        entrypoints_desc.add(EntryPointDesc([file], identifier))
                if not files:
                    sys.exit(f"No file with description of entry points for '{group}' were found")

        # Process sources in separate process.
        sources_queue = multiprocessing.Queue()
        sources_process = multiprocessing.Process(target=self.__prepare_sources, name="sources",
                                                  args=(sources_queue,))
        sources_process.start()
        sources_process.join()
        # Wait here since this information may reduce future preparation work.

        if not sources_queue.empty():
            data = sources_queue.get()
            if not specific_functions:
                specific_functions = data.get(SOURCE_QUEUE_FUNCTIONS)
            specific_sources = data.get(SOURCE_QUEUE_FILES)
            qualifier_resources = data.get(SOURCE_QUEUE_QUALIFIER_RESOURCES)
            builder_resources = data.get(SOURCE_QUEUE_BUILDER_RESOURCES)
            self.build_results = data.get(SOURCE_QUEUE_RESULTS)
        else:
            if not sources_process.exitcode:
                self.logger.error(
                    "Sanity check failed: builder data is missed with none-error exit code")
                sys.exit(sources_process.exitcode)

        if sources_process.exitcode:
            self.logger.error("Source directories were not prepared")
            sys.exit(sources_process.exitcode)

        if specific_functions:
            static_callers = set()
            for func in specific_functions:
                static_callers.add(func + STATIC_SUFFIX)
            specific_functions.update(static_callers)

        self.logger.info("Preparing verification tasks based on the given configuration")
        preparator_processes = self.config.get(COMPONENT_PREPARATOR, {}).get(TAG_PROCESSES,
                                                                             max_cores)
        self.logger.debug(f"Starting scheduler for verification tasks preparation with "
                          f"{preparator_processes} processes")

        find_coverage = self.config.get(COMPONENT_COVERAGE, {}).get(TAG_MAX_COVERAGE, False)
        if find_coverage:
            if PROPERTY_COVERAGE in rules and len(rules) > 1:
                # Do not create specific launch to find coverage.
                rules.remove(PROPERTY_COVERAGE)

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
            with open(preparation_config_file, encoding="ascii") as file_obj:
                preparation_config = json.load(file_obj)
        else:
            preparation_config = {}

        for entry_desc in entrypoints_desc:
            if specific_sources:
                is_skip = True
                for file in specific_sources:
                    for subsystem in entry_desc.subsystems:
                        if subsystem in file:
                            is_skip = False
                            break
                if is_skip:
                    self.logger.debug(f"Skipping subsystem '{entry_desc.id}' "
                                      f"because it does not relate with the checking commits")
                    continue
            main_generator = MainGenerator(self.config, entry_desc.data, self.properties_desc)
            main_generator.process_sources()
            for rule in rules:
                strategy = main_generator.get_strategy(rule)
                mode = self.__get_mode(rule)
                prop_plain_name = re.sub('\\W+', '_', rule)
                object_name = f"{entry_desc.short_name}_{prop_plain_name}_{strategy}"
                main_file_name = os.path.join(DEFAULT_MAIN_DIR, f"{object_name}.c")
                entrypoints = main_generator.generate_main(strategy, main_file_name, rule)
                model = self.__get_file_for_system(self.models_dir, f"{rule}.c")
                common_file = self.__get_file_for_system(self.models_dir, COMMON_HEADER_FOR_RULES)
                cil_file = os.path.abspath(os.path.join(DEFAULT_CIL_DIR, f"{object_name}.i"))
                try:
                    while True:
                        for i in range(preparator_processes):
                            if process_pool[i] and not process_pool[i].is_alive():
                                process_pool[i].join()
                                process_pool[i] = None
                            if not process_pool[i]:
                                if is_cached and os.path.exists(cil_file):
                                    self.logger.debug(f"Using cached CIL-file {cil_file}")
                                else:
                                    self.logger.debug(
                                        f"Generating verification task {cil_file} for entrypoints "
                                        f"{entry_desc.id}, rule {rule}")
                                    preparator = Preparator(
                                        self.install_dir, self.config,
                                        subdirectory_patterns=entry_desc.subsystems, model=model,
                                        main_file=main_file_name, output_file=cil_file,
                                        preparation_config=preparation_config,
                                        common_file=common_file, build_results=self.build_results)
                                    process_pool[i] = multiprocessing.Process(
                                        target=preparator.prepare_task, name=cil_file,
                                        args=(resource_queue,))
                                    process_pool[i].start()
                                raise NestedLoop
                        sleep(BUSY_WAITING_INTERVAL)
                except NestedLoop:
                    pass
                except Exception as exception:
                    self.logger.error(f"Could not prepare verification task: {exception}",
                                      exc_info=True)
                    kill_launches(process_pool)
                for entrypoint in entrypoints:
                    path_to_verifier = self.get_tool_path(
                        os.path.join(mode, DEFAULT_CPACHECKER_SCRIPTS_PATH))

                    if not specific_functions or \
                            entrypoint.replace(ENTRY_POINT_SUFFIX, "") in specific_functions or \
                            entrypoint == DEFAULT_MAIN:
                        launches.append(VerificationTask(entry_desc, rule, self.__get_mode(rule),
                                                         entrypoint, path_to_verifier, cil_file))
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
                    self.logger.warning(f"The file {launch.cil_file} was not found, "
                                        f"skip the corresponding launch")
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
        component_attrs = {COMPONENT_PREPARATOR: {}}
        build_commands = {}
        while not resource_queue.empty():
            prep_data = resource_queue.get()
            preparator_wall_time = prep_data.get(TAG_WALL_TIME, 0.0)
            preparator_cpu_time = prep_data.get(TAG_CPU_TIME, 0.0)
            preparator_memory = prep_data.get(TAG_MEMORY_USAGE, 0)
            preparation_memory_usage_all.append(preparator_memory)
            preparation_cpu_time += preparator_cpu_time
            if TAG_LOG_FILE in prep_data:
                cil_file = prep_data.get(TAG_CIL_FILE, "")
                attrs = []
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
                with open(prep_data[TAG_PREP_RESULTS], encoding="utf8") as file_obj:
                    data = json.load(file_obj)
                    for cmd, args in data.items():
                        if cmd not in build_commands:
                            build_commands[cmd] = args
                        else:
                            for index, arg in enumerate(args):
                                build_commands[cmd][index] = build_commands[cmd][index] or arg

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
            self.logger.info(f"Number of build commands: {overall_build_commands}; "
                             f"potentially can be used (not ignored): {potential_build_commands}; "
                             f"filtered for checked subsystems: {filtered_build_commands}; "
                             f"compiled: {compiled_build_commands}; "
                             f"processed: {processed_build_commands}")
            # TODO: upload those unused build commands for common coverage data

        for memory_usage in sorted(preparation_memory_usage_all):
            preparation_memory_usage += memory_usage
            counter += 1
            if counter > preparator_processes:
                break

        if backup_read:
            self.logger.info("Restoring from backup copy")
            backup_files = glob.glob(os.path.join(self.work_dir, f"{DEFAULT_BACKUP_PREFIX}*"))
            for file in backup_files:
                with open(file, "r", errors='ignore', encoding="ascii") as f_res:
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
                with open(self.backup, "a", encoding="ascii") as f_report:
                    for result in results:
                        f_report.write(str(result) + "\n")
            if results:
                self.logger.info(f"Successfully restored {len(results)} results")
            else:
                self.logger.info("No results were restored")

        self.logger.info("Preparation of verification tasks has been completed")
        preparation_wall_time = time.time() - preparator_start_wall
        self.logger.debug(f"Preparation wall time: "
                          f"{round(preparation_wall_time, 2)} seconds")
        self.logger.debug(f"Preparation CPU time: "
                          f"{round(preparation_cpu_time, 2)} seconds")
        self.logger.debug(f"Preparation memory usage: "
                          f"{round(preparation_memory_usage / 2 ** 20, 2)} Mb")
        self.logger.info("Starting to solve verification tasks")
        self.logger.info(f"Expected number of verifier launches is {len(launches)}")

        # Prepare BenchExec commands.
        path_to_benchexec = self.get_tool_path(self._get_tool_default_path(BENCHEXEC),
                                               self.config.get(TAG_TOOLS, {}).get(BENCHEXEC))
        self.logger.debug(f"Using BenchExec, found in: '{path_to_benchexec}'")
        os.environ["PATH"] += os.pathsep + path_to_benchexec
        benchmark = {}
        for prop in self.properties_desc.get_properties():
            # Specify resource limitations.
            benchmark[prop] = self.__create_benchmark_config(time_limit, core_limit, memory_limit)
            rundefinition = ElementTree.SubElement(benchmark[prop], "rundefinition")
            ElementTree.SubElement(rundefinition, "option", {"name": "-heap"}).text = \
                f"{heap_limit}m"
            if internal_time_limit > 0:
                ElementTree.SubElement(rundefinition, "option", {"name": "-timelimit"}).text = \
                    str(internal_time_limit)

            # Create links to the properties.
            for file in glob.glob(os.path.join(self.root_dir, DEFAULT_PROPERTIES_DIR,
                                               DEFAULT_AUTOMATA_DIR, "*")):
                if os.path.isfile(file):
                    shutil.copy(file, DEFAULT_AUTOMATA_DIR)
            if self.system_id:
                for file in glob.glob(os.path.join(self.plugin_dir, self.system_id,
                                                   DEFAULT_PROPERTIES_DIR, DEFAULT_AUTOMATA_DIR,
                                                   "*")):
                    if os.path.isfile(file):
                        shutil.copy(file, DEFAULT_AUTOMATA_DIR)

            # Get options from files.
            self.__parse_verifier_options(prop, rundefinition)

        self.logger.debug(f"Starting scheduler for verifier launches with {number_of_processes} "
                          f"processes")
        counter = 1
        number_of_launches = len(launches)
        if number_of_launches == 0:
            self.logger.warning("No launches were set by the given configuration")
            sys.exit(0)
        queue = multiprocessing.Queue()
        if self.scheduler == SCHEDULER_CLOUD:
            mea_processes = self.config.get(COMPONENT_MEA, {}).get(TAG_PARALLEL_LAUNCHES,
                                                                   self.cpu_cores)
        else:
            mea_processes = max(1, max_cores - number_of_processes)
        filtering_process = multiprocessing.Process(target=self.__filter_scheduler, name="MEA",
                                                    args=(mea_processes, queue))
        filtering_process.start()

        if self.scheduler == SCHEDULER_CLOUD:
            launch_groups = {}
            for launch in launches:
                mode = self.__get_mode(launch.rule)
                if mode in launch_groups:
                    launch_groups[mode].append(launch)
                else:
                    launch_groups[mode] = [launch]
            del launches
            self.logger.info(f"Divided all tasks into {len(launch_groups)} group(s) for solving on "
                             f"cloud")
            process_pool = []
            for mode, launches in launch_groups.items():
                process_single_group = multiprocessing.Process(
                    target=self.__process_single_group, name=mode,
                    args=(mode, launches, time_limit, memory_limit, core_limit, heap_limit,
                          internal_time_limit, queue))
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
                                self.logger.info(f"Established connection to group "
                                                 f"{len(solving_groups)}")
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
                            self.logger.info(
                                f"Scheduling new launch: subsystem '{launch.entry_desc.id}'"
                                f", rule '{launch.rule}', entrypoint '{launch.entrypoint}' "
                                f"({round(percent, 2)}% remains)")
                            counter += 1
                            process_pool[i] = multiprocessing.Process(
                                target=self.local_launch, name=launch.name,
                                args=(launch, benchmark[launch.rule], queue))
                            process_pool[i].start()
                            if len(launches) == 0:
                                raise NestedLoop
                    sleep(BUSY_WAITING_INTERVAL)
            except NestedLoop:
                # All entry points has been checked.
                wait_for_launches(process_pool)
                self._get_from_queue_into_list(queue, results)
            except Exception as exception:
                self.logger.error(f"Process scheduler was terminated: {exception}", exc_info=True)
                filtering_process.terminate()
                kill_launches(process_pool)
                sys.exit(1)
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
        self.logger.debug(f"Overall wall time of script: {overall_wall_time}")
        self.logger.debug(f"Overall CPU time of script: {overall_cpu_time}")
        self.logger.info("Solving of verification tasks has been completed")

        report_launches, result_archive, report_components, short_report, report_resources = \
            self._get_results_names()

        self.logger.debug("Processing results")
        cov_lines = {}
        cov_funcs = {}
        stats_by_rules = {}
        cov_cpu = 0
        wall_cov = 0
        cov_mem_array = []
        for rule in rules:
            if rule == PROPERTY_COVERAGE:
                continue
            stats_by_rules[rule] = GlobalStatistics()
        for result in results:
            if result.rule == PROPERTY_COVERAGE:
                key = self._get_none_rule_key(result)
                cov_lines[key] = result.cov_lines
                cov_funcs[key] = result.cov_funcs
            else:
                stats_by_rules[result.rule].add_result(result)
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

        self._print_launches_report(report_launches, report_resources, results, cov_lines,
                                    cov_funcs)
        self.logger.info(f"Preparing report on components into file: '{report_components}'")
        with open(report_components, "w", encoding="ascii") as f_report:
            f_report.write("Name;CPU;Wall;Memory\n")  # Header.
            f_report.write(
                f"{COMPONENT_PREPARATOR};{round(preparation_cpu_time, ROUND_DIGITS)};"
                f"{round(preparation_wall_time, ROUND_DIGITS)};{preparation_memory_usage}\n")
            f_report.write(
                f"{COMPONENT_LAUNCHER};{round(overall_cpu_time, ROUND_DIGITS)};"
                f"{round(overall_wall_time, ROUND_DIGITS)};"
                f"{int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024}\n")
            f_report.write(
                f"{COMPONENT_MEA};{round(mea_cpu, ROUND_DIGITS)};{round(mea_wall, ROUND_DIGITS)};"
                f"{mea_memory}\n")
            f_report.write(
                f"{COMPONENT_COVERAGE};{round(cov_cpu, ROUND_DIGITS)};"
                f"{round(wall_cov, ROUND_DIGITS)};{cov_mem}\n")
            if qualifier_resources:
                f_report.write(
                    f"{COMPONENT_QUALIFIER};"
                    f"{round(qualifier_resources[TAG_CPU_TIME], ROUND_DIGITS)};"
                    f"{round(qualifier_resources[TAG_WALL_TIME], ROUND_DIGITS)};"
                    f"{round(qualifier_resources[TAG_MEMORY_USAGE], ROUND_DIGITS)}\n")
            if builder_resources:
                f_report.write(
                    f"{COMPONENT_BUILDER};{round(builder_resources[TAG_CPU_TIME], ROUND_DIGITS)};"
                    f"{round(builder_resources[TAG_WALL_TIME], ROUND_DIGITS)};"
                    f"{round(builder_resources[TAG_MEMORY_USAGE], ROUND_DIGITS)}\n")

        self.logger.info(f"Preparing short report into file: '{short_report}'")
        with open(short_report, "w", encoding="ascii") as f_report:
            f_report.write("Rule;Safes;Unsafes;Unknowns;Relevant;Traces;Filtered;CPU;Wall;Mem\n")
            overall_stats = GlobalStatistics()
            for rule, info in sorted(stats_by_rules.items()):
                info.sum_memory()
                f_report.write(f"{rule};{info}\n")
                overall_stats.sum(info)
            f_report.write(f"Overall;{overall_stats}\n")

        self.logger.info(f"Exporting results into archive: '{result_archive}'")

        config = {
            TAG_CONFIG_MEMORY_LIMIT: str(memory_limit) + "GB",
            TAG_CONFIG_CPU_TIME_LIMIT: time_limit,
            TAG_CONFIG_CPU_CORES_LIMIT: core_limit
        }
        exporter = Exporter(self.config, DEFAULT_EXPORT_DIR, self.install_dir,
                            properties_desc=self.properties_desc)
        exporter.export(report_launches, report_resources, report_components, result_archive,
                        unknown_desc={COMPONENT_PREPARATOR: preparator_unknowns},
                        component_attrs=component_attrs, verifier_config=config)

        uploader_config = self.config.get(UPLOADER, {})
        if uploader_config and uploader_config.get(TAG_UPLOADER_UPLOAD_RESULTS, False):
            self._upload_results(uploader_config, result_archive)

        if not self.debug:
            self.logger.info("Cleaning working directories")
            shutil.rmtree(DEFAULT_MAIN_DIR, ignore_errors=True)
            shutil.rmtree(DEFAULT_EXPORT_DIR, ignore_errors=True)
            if self.backup and os.path.exists(self.backup):
                os.remove(self.backup)
            shutil.rmtree(DEFAULT_LAUNCHES_DIR, ignore_errors=True)
            shutil.rmtree(DEFAULT_PREPROCESS_DIR, ignore_errors=True)
        self.logger.info(f"Finishing verification of '{self.config_file}' configuration")
        os.chdir(self.root_dir)
