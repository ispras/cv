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

"""
Component for launching benchmark and processing its results.
"""

import resource

from aux.common import *
from components.exporter import Exporter
from components.launcher import *
from models.verification_result import *


TAG_BENCHMARK_CLIENT_DIR = "client dir"
TAG_TOOL_DIR = "tool dir"
TAG_OUTPUT_DIR = "output dir"
TAG_TASKS_DIR = "tasks dir"
TAG_BENCHMARK_FILE = "benchmark file"
TAG_TOOL_NAME = "tool"
TAG_POLL_INTERVAL = "poll interval"
TAG_PROCESS_WITNESSES_ONLY = "process witnesses only"
TAG_SPECIFIED_PROPERTY = "specified property"


class BenchmarkLauncher(Launcher):
    """
    Main component, which launches the given benchmark if needed and processes results.
    """
    def __init__(self, config_file, additional_config: dict, is_launch=False):
        super().__init__(COMPONENT_BENCHMARK_LAUNCHER, config_file)
        if not os.path.exists(self.work_dir):
            os.makedirs(self.work_dir, exist_ok=True)

        # Propagate command line arguments.
        for name, val in additional_config.items():
            if val:
                self.component_config[name] = val

        # Mandatory arguments.
        self.output_dir = os.path.abspath(self.component_config[TAG_OUTPUT_DIR])
        self.tasks_dir = os.path.abspath(self.component_config[TAG_TASKS_DIR])

        # Optional arguments.
        self.tool = self.component_config.get(TAG_TOOL_NAME, DEFAULT_VERIFIER_TOOL)

        self.poll_interval = self.component_config.get(TAG_POLL_INTERVAL, BUSY_WAITING_INTERVAL)

        self.process_witnesses_only = self.component_config.get(TAG_PROCESS_WITNESSES_ONLY, False)
        self.specified_property = self.component_config.get(TAG_SPECIFIED_PROPERTY, "unknown")

        self.is_launch = is_launch
        self.process_dir = None
        if is_launch:
            tools_dir = os.path.abspath(self.component_config[TAG_TOOL_DIR])
            self.logger.debug(f"Using tool directory {tools_dir}")
            os.chdir(tools_dir)
        else:
            self.logger.debug(f"Using working directory {self.work_dir}")
            os.chdir(self.work_dir)

        self.logger.debug(f"Create a symbolic links for source directory {self.tasks_dir}")
        update_symlink(self.tasks_dir)
        for task_dir_in in glob.glob(os.path.join(self.tasks_dir, "*")):
            if os.path.isdir(task_dir_in):
                update_symlink(task_dir_in)

    def __process_single_launch_results(self, result: VerificationResults, group_directory, queue,
                                        columns, source_file, task_name, benchmark_name):
        assert self.process_dir
        files = []
        directories = glob.glob(os.path.join(group_directory, f"{benchmark_name}.*files"))
        if not directories:
            if self.process_witnesses_only:
                files.append(source_file)
            else:
                self.logger.error(f"Output directory '{group_directory}' format is not supported")
                sys.exit(0)
        for directory in directories:
            for pattern in [f"{task_name}.{result.entrypoint}", f"{result.entrypoint}"]:
                for name in [f"{pattern}.log", f"{pattern}.files", f"{pattern}"]:
                    name = os.path.join(directory, name)
                    if os.path.exists(name):
                        files.append(name)
        launch_directory = self._copy_result_files(files, self.process_dir)

        result.work_dir = launch_directory
        result.parse_output_dir(launch_directory, self.install_dir, self.result_dir_et, columns)
        self._process_coverage(result, launch_directory, [self.tasks_dir], source_file)
        if result.initial_traces > 1:
            result.filter_traces(launch_directory, self.install_dir, self.result_dir_et)
        queue.put(result)
        sys.exit(0)

    def __parse_result_file(self, file: str, group_directory: str):
        self.logger.info(f"Processing result file {file}")
        tree = ElementTree.ElementTree()
        tree.parse(file)
        root = tree.getroot()
        results = []
        global_spec = None
        is_spec = False
        task_name = root.attrib.get('name', '')
        benchmark_name = root.attrib.get('benchmarkname', '')
        block_id = root.attrib.get('block', "NONE")
        memory_limit = root.attrib.get('memlimit', None)
        time_limit = root.attrib.get('timelimit', None)
        cpu_cores_limit = root.attrib.get('cpuCores', None)
        options = root.attrib.get('options', '')
        config = {}
        if memory_limit:
            config[TAG_CONFIG_MEMORY_LIMIT] = memory_limit
        if time_limit:
            config[TAG_CONFIG_CPU_TIME_LIMIT] = time_limit
        if cpu_cores_limit:
            config[TAG_CONFIG_CPU_CORES_LIMIT] = cpu_cores_limit
        if options:
            config[TAG_CONFIG_OPTIONS] = options

        if block_id == "NONE":
            return None
        self.job_name_suffix = task_name
        if task_name.endswith(block_id):
            task_name = task_name[:-(len(block_id) + 1)]
            if block_id == "0":
                self.job_name_suffix = task_name
        for option in options.split():
            if is_spec:
                global_spec = str(os.path.basename(option))
                if global_spec.endswith('.spc') or global_spec.endswith('.prp'):
                    global_spec = global_spec[:-4]
                break
            if option == "-spec":
                is_spec = True

        queue = multiprocessing.Queue()
        process_pool = []
        for i in range(self.cpu_cores):
            process_pool.append(None)

        for run in root.findall('./run'):
            file_name = os.path.realpath(os.path.normpath(os.path.abspath(run.attrib['name'])))
            file_name_base = os.path.basename(file_name)
            properties = run.attrib.get('properties', global_spec)
            result = VerificationResults(None, self.config)
            result.entrypoint = file_name_base
            result.rule = properties
            result.id = "."

            columns = run.findall('./column')

            try:
                while True:
                    for i in range(self.cpu_cores):
                        if process_pool[i] and not process_pool[i].is_alive():
                            process_pool[i].join()
                            process_pool[i] = None
                        if not process_pool[i]:
                            process_pool[i] = multiprocessing.Process(
                                target=self.__process_single_launch_results, name=result.entrypoint,
                                args=(result, group_directory, queue, columns, file_name, task_name,
                                      benchmark_name))
                            process_pool[i].start()
                            raise NestedLoop
                    time.sleep(self.poll_interval)
            except NestedLoop:
                self._get_from_queue_into_list(queue, results)
            except Exception as exception:
                self.logger.error(f"Error during processing results: {exception}", exc_info=True)
                kill_launches(process_pool)
        wait_for_launches(process_pool)
        self._get_from_queue_into_list(queue, results)

        self.logger.debug("Processing results")
        coverage_resources = {TAG_CPU_TIME: 0.0, TAG_WALL_TIME: 0.0, TAG_MEMORY_USAGE: 0}
        mea_resources = {TAG_CPU_TIME: 0.0, TAG_WALL_TIME: 0.0, TAG_MEMORY_USAGE: 0}
        for result in results:
            coverage_resources[TAG_MEMORY_USAGE] = \
                max(coverage_resources[TAG_MEMORY_USAGE],
                    result.coverage_resources.get(TAG_MEMORY_USAGE, 0))
            mea_resources[TAG_MEMORY_USAGE] = max(mea_resources[TAG_MEMORY_USAGE],
                                                  result.mea_resources.get(TAG_MEMORY_USAGE, 0))
            coverage_resources[TAG_CPU_TIME] += result.coverage_resources.get(TAG_CPU_TIME, 0.0)
            coverage_resources[TAG_WALL_TIME] += result.coverage_resources.get(TAG_WALL_TIME, 0.0)
            mea_resources[TAG_CPU_TIME] += result.mea_resources.get(TAG_CPU_TIME, 0.0)
            mea_resources[TAG_WALL_TIME] += result.mea_resources.get(TAG_WALL_TIME, 0.0)
        report_launches, result_archive, report_components, _, report_resources = \
            self._get_results_names()
        self._print_launches_report(report_launches, report_resources, results)
        overall_cpu_time = time.process_time() - self.start_cpu_time
        overall_wall_time = time.time() - self.start_time
        self.logger.info(f"Preparing report on components into file: '{report_components}'")
        with open(report_components, "w", encoding='ascii') as f_report:
            f_report.write("Name;CPU;Wall;Memory\n")  # Header.
            f_report.write(f"{COMPONENT_BENCHMARK_LAUNCHER};"
                           f"{round(overall_cpu_time, ROUND_DIGITS)};"
                           f"{round(overall_wall_time, ROUND_DIGITS)};"
                           f"{int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024}\n")
            f_report.write(f"{COMPONENT_MEA};"
                           f"{round(mea_resources[TAG_CPU_TIME], ROUND_DIGITS)};"
                           f"{round(mea_resources[TAG_WALL_TIME], ROUND_DIGITS)};"
                           f"{mea_resources[TAG_MEMORY_USAGE]}\n")
            f_report.write(f"{COMPONENT_COVERAGE};"
                           f"{round(coverage_resources[TAG_CPU_TIME], ROUND_DIGITS)};"
                           f"{round(coverage_resources[TAG_WALL_TIME], ROUND_DIGITS)};"
                           f"{coverage_resources[TAG_MEMORY_USAGE]}\n")

        self.logger.info(f"Exporting results into archive: '{result_archive}'")
        upload_process = multiprocessing.Process(target=self.__upload, name="upload",
                                                 args=(report_launches, report_resources,
                                                       report_components, result_archive, config))
        upload_process.start()
        upload_process.join()
        return result_archive

    def __upload(self, report_launches, report_resources, report_components, result_archive,
                 config):
        exporter = Exporter(self.config, DEFAULT_EXPORT_DIR, self.install_dir, tool=self.tool)
        exporter.export(report_launches, report_resources, report_components, result_archive,
                        verifier_config=config)

    def launch_benchmark(self):
        """
        Launch benchmark.
        """
        if not self.scheduler or not self.scheduler == SCHEDULER_CLOUD:
            sys.exit(f"Scheduler '{self.scheduler}' is not supported "
                     f"(only cloud scheduler is currently supported)")
        exec_dir = os.path.abspath(self.component_config[TAG_BENCHMARK_CLIENT_DIR])
        benchmark_name = os.path.abspath(self.component_config[TAG_BENCHMARK_FILE])
        self.logger.info(f"Launching benchmark {benchmark_name}")

        benchmark_name_rel = os.path.basename(benchmark_name)
        if os.path.exists(benchmark_name_rel):
            os.remove(benchmark_name_rel)
        shutil.copy(benchmark_name, benchmark_name_rel)

        os.makedirs(self.output_dir, exist_ok=True)

        shutil.rmtree(self.output_dir)
        os.makedirs(self.output_dir)

        log_file_name = os.path.join(self.output_dir, CLOUD_BENCHMARK_LOG)
        with open(log_file_name, 'w', encoding='utf8') as f_log:
            # Launch group.
            command = f"python3 {exec_dir}/scripts/benchmark.py --no-compress-results " \
                      f"-o {self.output_dir} --container {benchmark_name_rel} {self.benchmark_args}"
            self.logger.debug(f"Launching benchmark: {command}")
            subprocess.check_call(command, shell=True, stderr=f_log, stdout=f_log)

    def __get_entry_point_from_witness(self, witness: str) -> str:
        base_name = os.path.basename(witness)
        rel_path = os.path.dirname(witness.replace(self.output_dir + os.sep, ""))
        potential_name = witness.replace(self.output_dir, "").replace(base_name, "").\
            replace("output", "").replace(os.sep, "")
        if potential_name:
            # Example: benchmark.*.logfiles/<source_file>.files/output/witness.graphml
            return potential_name.replace(".files", "")
        potential_name = base_name.replace(".graphml", "").replace("witness", "").replace(".", "")
        if potential_name:
            # Example: witness.<id>.graphml
            return rel_path.replace(base_name, "").replace("output", "") + potential_name
        return rel_path

    def __process_witnesses_only(self, uploader_config, is_upload):
        witnesses = subprocess.check_output(f"find {self.output_dir} -name *graphml",
                                            shell=True).decode(errors='ignore').rstrip().split("\n")
        queue = multiprocessing.Queue()
        process_pool = []
        results = []
        if COMPONENT_MEA not in self.config:
            self.config[COMPONENT_MEA] = {}
        self.config[COMPONENT_MEA][TAG_SOURCE_DIR] = self.tasks_dir
        self.process_dir = os.path.abspath(tempfile.mkdtemp(dir=self.work_dir))
        for i in range(self.cpu_cores):
            process_pool.append(None)
        for witness in witnesses:
            result = VerificationResults(None, self.config)
            result.entrypoint = self.__get_entry_point_from_witness(witness)
            result.rule = self.specified_property
            result.id = "."
            result.termination_reason = TERMINATION_SUCCESS

            try:
                while True:
                    for i in range(self.cpu_cores):
                        if process_pool[i] and not process_pool[i].is_alive():
                            process_pool[i].join()
                            process_pool[i] = None
                        if not process_pool[i]:
                            process_pool[i] = multiprocessing.Process(
                                target=self.__process_single_launch_results,
                                name=result.entrypoint,
                                args=(result, self.output_dir, queue, None, witness, "", ""))
                            process_pool[i].start()
                            raise NestedLoop
                    time.sleep(self.poll_interval)
            except NestedLoop:
                self._get_from_queue_into_list(queue, results)
            except Exception as exception:
                self.logger.error(f"Error during processing results: {exception}", exc_info=True)
                kill_launches(process_pool)
        wait_for_launches(process_pool)
        self._get_from_queue_into_list(queue, results)
        self.logger.debug("Processing results")

        coverage_resources = {TAG_CPU_TIME: 0.0, TAG_WALL_TIME: 0.0, TAG_MEMORY_USAGE: 0}
        mea_resources = {TAG_CPU_TIME: 0.0, TAG_WALL_TIME: 0.0, TAG_MEMORY_USAGE: 0}
        for result in results:
            coverage_resources[TAG_MEMORY_USAGE] = \
                max(coverage_resources[TAG_MEMORY_USAGE],
                    result.coverage_resources.get(TAG_MEMORY_USAGE, 0))
            mea_resources[TAG_MEMORY_USAGE] = max(mea_resources[TAG_MEMORY_USAGE],
                                                  result.mea_resources.get(TAG_MEMORY_USAGE, 0))
            coverage_resources[TAG_CPU_TIME] += result.coverage_resources.get(TAG_CPU_TIME, 0.0)
            coverage_resources[TAG_WALL_TIME] += result.coverage_resources.get(TAG_WALL_TIME, 0.0)
            mea_resources[TAG_CPU_TIME] += result.mea_resources.get(TAG_CPU_TIME, 0.0)
            mea_resources[TAG_WALL_TIME] += result.mea_resources.get(TAG_WALL_TIME, 0.0)
        report_launches, result_archive, report_components, _, report_resources = \
            self._get_results_names()
        self._print_launches_report(report_launches, report_resources, results)
        overall_cpu_time = time.process_time() - self.start_cpu_time
        overall_wall_time = time.time() - self.start_time
        self.logger.info(f"Preparing report on components into file: '{report_components}'")
        with open(report_components, "w", encoding='ascii') as f_report:
            f_report.write("Name;CPU;Wall;Memory\n")  # Header.
            f_report.write(f"{COMPONENT_BENCHMARK_LAUNCHER};"
                           f"{round(overall_cpu_time, ROUND_DIGITS)};"
                           f"{round(overall_wall_time, ROUND_DIGITS)};"
                           f"{int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024}\n")
            f_report.write(f"{COMPONENT_MEA};"
                           f"{round(mea_resources[TAG_CPU_TIME], ROUND_DIGITS)};"
                           f"{round(mea_resources[TAG_WALL_TIME], ROUND_DIGITS)};"
                           f"{mea_resources[TAG_MEMORY_USAGE]}\n")
            f_report.write(f"{COMPONENT_COVERAGE};"
                           f"{round(coverage_resources[TAG_CPU_TIME], ROUND_DIGITS)};"
                           f"{round(coverage_resources[TAG_WALL_TIME], ROUND_DIGITS)};"
                           f"{coverage_resources[TAG_MEMORY_USAGE]}\n")
        self.logger.info(f"Exporting results into archive: '{result_archive}'")
        upload_process = multiprocessing.Process(target=self.__upload, name="upload",
                                                 args=(report_launches, report_resources,
                                                       report_components, result_archive, {}))
        upload_process.start()
        upload_process.join()
        if is_upload:
            self._upload_results(uploader_config, result_archive)
        if not self.debug:
            shutil.rmtree(self.process_dir, ignore_errors=True)

    def process_results(self):
        """
        Process benchmark results.
        """
        xml_files = glob.glob(os.path.join(self.output_dir, '*results.*.xml'))
        uploader_config = self.config.get(UPLOADER, {})
        is_upload = uploader_config and uploader_config.get(TAG_UPLOADER_UPLOAD_RESULTS, False)
        if self.process_witnesses_only:
            self.__process_witnesses_only(uploader_config, is_upload)
        else:
            for file in xml_files:
                self.process_dir = os.path.abspath(tempfile.mkdtemp(dir=self.work_dir))
                result_archive = self.__parse_result_file(file, self.output_dir)
                if is_upload and result_archive:
                    self._upload_results(uploader_config, result_archive)
                if not self.debug:
                    shutil.rmtree(self.process_dir, ignore_errors=True)
        if not self.debug:
            clear_symlink(self.tasks_dir)
            for task_dir_in in glob.glob(os.path.join(self.tasks_dir, "*")):
                clear_symlink(task_dir_in)
