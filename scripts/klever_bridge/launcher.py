#
# CV is a framework for continuous verification.
#
# Copyright (c) 2018-2023 ISP RAS (http://www.ispras.ru)
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

from aux.common import *
from components.benchmark_launcher import BenchmarkLauncher
from components.launcher import *
from klever_bridge.index_tasks import index_klever_tasks

TAG_JOB_ID = "job id"
TAG_TASK_ARGS = "args"
TAG_TASK_XML = "xml"
CIL_FILE = "cil.i"

JOBS_DIR = "jobs"
JOB_RES_FILE = "runexec stdout.log"
KLEVER_COMPONENT = "Klever"
KLEVER_WORK_DIR = "klever-core-work-dir"
KERNEL_DIR = "kernel dir"


class KleverLauncher(BenchmarkLauncher):
    """
    Main component, which launches the given Klever benchmark if needed and processes results.
    """
    def __init__(self, config_file, additional_config: dict, is_launch=False):
        super().__init__(config_file, additional_config, is_launch)
        self.job_id = self.component_config.get(TAG_JOB_ID, None)
        self.kernel_dir = os.path.realpath(self.component_config.get(KERNEL_DIR, ""))

    @staticmethod
    def __parse_memory(memory: str) -> str:
        if memory and memory.endswith("B"):
            memory = int(memory[:-1])
            memory = round(memory / 10 ** 9, 2)
            return f"{memory}GB"
        return memory

    def __process_single_klever_result(self, result: VerificationResults, output_dir, queue,
                                       columns):
        assert self.process_dir
        files = [output_dir]
        for file in glob.glob(os.path.join(output_dir, "*files")):
            if file.endswith(".log"):
                files.append(file)
        if COMPONENT_MEA not in self.config:
            self.config[COMPONENT_MEA] = {}
        self.config[COMPONENT_MEA][TAG_SOURCE_DIR] = os.path.join(output_dir, os.path.pardir)
        launch_directory = self._copy_result_files(files, self.process_dir)

        result.work_dir = launch_directory
        result.parse_output_dir(launch_directory, self.install_dir, self.result_dir_et, columns)
        jobs_dir = os.path.join(self.output_dir, os.path.pardir, JOBS_DIR, self.job_id, KLEVER_WORK_DIR)
        source_dir = os.path.join(self.tasks_dir, self.kernel_dir.lstrip(os.sep))
        self._process_coverage(result, launch_directory, [source_dir, self.tasks_dir,
                                                          os.path.join(output_dir, os.path.pardir)],
                               work_dir=jobs_dir)
        if result.initial_traces > 1:
            result.filter_traces(launch_directory, self.install_dir, self.result_dir_et)
        queue.put(result)
        sys.exit(0)

    def __parse_tasks_dir(self, processed_tasks: dict, job_id: str):
        queue = multiprocessing.Queue()
        process_pool = []
        results = []
        job_config = {}
        for i in range(self.cpu_cores):
            process_pool.append(None)

        for output_dir, tasks_args in processed_tasks.items():
            xml_file = tasks_args[TAG_TASK_XML]
            module, prop, _ = tasks_args[TAG_TASK_ARGS]
            tree = ElementTree.ElementTree()
            tree.parse(xml_file)
            root = tree.getroot()
            if not job_config:
                memory_limit = self.__parse_memory(root.attrib.get('memlimit', None))
                time_limit = root.attrib.get('timelimit', None)
                cpu_cores_limit = root.attrib.get('cpuCores', None)
                options = root.attrib.get('options', '')
                if memory_limit:
                    job_config[TAG_CONFIG_MEMORY_LIMIT] = memory_limit
                if time_limit:
                    job_config[TAG_CONFIG_CPU_TIME_LIMIT] = time_limit
                if cpu_cores_limit:
                    job_config[TAG_CONFIG_CPU_CORES_LIMIT] = cpu_cores_limit
                if options:
                    job_config[TAG_CONFIG_OPTIONS] = options

            for run in root.findall('./run'):
                result = VerificationResults(None, self.config)
                result.entrypoint = module
                result.rule = prop
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
                                    target=self.__process_single_klever_result,
                                    name=result.entrypoint,
                                    args=(result, output_dir, queue, columns))
                                process_pool[i].start()
                                raise NestedLoop
                        time.sleep(self.poll_interval)
                except NestedLoop:
                    self._get_from_queue_into_list(queue, results)
                except Exception as exception:
                    self.logger.error(f"Error during processing results: {exception}",
                                      exc_info=True)
                    kill_launches(process_pool)
        wait_for_launches(process_pool)
        self._get_from_queue_into_list(queue, results)
        return self._export_results(results, job_config, self.__parse_job_resource_log(job_id))

    def __parse_job_resource_log(self, job_id: str) -> dict:
        job_resources = {TAG_CPU_TIME: 0.0, TAG_WALL_TIME: 0.0, TAG_MEMORY_USAGE: 0}
        if not job_id:
            return {}
        res_file = os.path.join(self.output_dir, os.path.pardir, JOBS_DIR, job_id,
                                JOB_RES_FILE)
        if not os.path.exists:
            self.logger.warning(f"File with job resources {res_file} does not exist")
            return {}
        with open(res_file, encoding="ascii") as res_fd:
            for line in res_fd.readlines():
                if line.startswith("walltime="):
                    job_resources[TAG_WALL_TIME] = float(line[9:-2])
                elif line.startswith("cputime="):
                    job_resources[TAG_CPU_TIME] = float(line[8:-2])
                elif line.startswith("memory="):
                    job_resources[TAG_MEMORY_USAGE] = float(line[7:-2])
        return {KLEVER_COMPONENT: job_resources}

    def process_results(self):
        """
        Process benchmark results.
        """
        # TODO: support launching klever tasks.
        self.logger.info("Indexing klever tasks files")
        jobs_to_tasks, tasks_to_attrs = index_klever_tasks(self.output_dir)
        for job_id in self.job_id.split(","):
            self.logger.info(f"Process job {job_id}")
            processed_tasks = {}
            self.job_name_suffix = job_id
            for task_id in jobs_to_tasks[job_id]:
                path_to_dir = os.path.join(self.output_dir, str(task_id), "output")
                xml_files = glob.glob(os.path.join(path_to_dir, '*results.*xml'))
                if len(xml_files) != 1:
                    self.logger.error(f"Abnormal number of xml reports {len(xml_files)} for task "
                                      f"{task_id} in a directory {path_to_dir}")
                    continue
                processed_tasks[path_to_dir] = {
                    TAG_TASK_XML: xml_files[0],
                    TAG_TASK_ARGS: tasks_to_attrs[task_id]
                }
            self.logger.info(f"Got {len(processed_tasks)} tasks")
            uploader_config = self.config.get(UPLOADER, {})
            is_upload = uploader_config and uploader_config.get(TAG_UPLOADER_UPLOAD_RESULTS, False)
            self.process_dir = os.path.abspath(tempfile.mkdtemp(dir=self.work_dir))
            result_archive = self.__parse_tasks_dir(processed_tasks, job_id)
            if is_upload and result_archive:
                self._upload_results(uploader_config, result_archive)
            if not self.debug:
                shutil.rmtree(self.process_dir, ignore_errors=True)
            if not self.debug:
                clear_symlink(self.tasks_dir)
                for task_dir_in in glob.glob(os.path.join(self.tasks_dir, "*")):
                    clear_symlink(task_dir_in)
