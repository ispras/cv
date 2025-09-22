# Continuous Verification Framework - processing and managing verification results.
# Repository: https://github.com/ispras/cv
#
# Copyright © 2025 Vitalii Mordan, ISP RAS
#
# SPDX-License-Identifier: Apache-2.0

"""
Component for launching benchmark and processing its results.
"""

# pylint: disable=attribute-defined-outside-init

import glob
import multiprocessing
import os
import shutil
import sys
import tempfile
import time
from xml.etree import ElementTree

from aux.common import NestedLoop, kill_launches, wait_for_launches, clear_symlink
from components.benchmark_launcher import BenchmarkLauncher
from components.component import Tool
from klever_bridge.index_tasks import index_klever_tasks
from models.tags import ComponentName, Tag
from models.verification_result import VerificationResults, Resource

TAG_JOB_ID = "job id"
TAG_TASK_ARGS = "args"
TAG_TASK_XML = "xml"
# CIL_FILE = "cil.i"

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
        if ComponentName.MEA not in self.config:
            self.config[ComponentName.MEA] = {}
        self.config[ComponentName.MEA][Tag.SOURCE_DIR] = os.path.join(output_dir, os.path.pardir)
        launch_directory = self._copy_result_files(files, self.process_dir)

        jobs_dir = os.path.join(self.output_dir, os.path.pardir, JOBS_DIR, self.job_id, KLEVER_WORK_DIR)
        source_dir = os.path.join(self.tasks_dir, self.kernel_dir.lstrip(os.sep))
        result.work_dir = launch_directory
        remove_src_prefixes = [
            os.path.realpath(source_dir),
            os.path.realpath(os.path.join(jobs_dir, "job", "root", "specifications")),
            os.path.realpath(os.path.join(jobs_dir, "job", "vtg"))
        ]
        result.parse_output_dir(launch_directory, self.install_dir, self.result_dir_et, columns, remove_src_prefixes)
        self._process_coverage(result, launch_directory, [source_dir, self.tasks_dir,
                                                          os.path.join(output_dir, os.path.pardir)],
                               work_dir=jobs_dir)
        if result.initial_traces > 1:
            result.filter_traces(launch_directory, self.install_dir, self.result_dir_et, remove_src_prefixes)
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
                    job_config[Tag.CONFIG_MEMORY_LIMIT] = memory_limit
                if time_limit:
                    job_config[Tag.CONFIG_CPU_TIME_LIMIT] = time_limit
                if cpu_cores_limit:
                    job_config[Tag.CONFIG_CPU_CORES_LIMIT] = cpu_cores_limit
                if options:
                    job_config[Tag.CONFIG_OPTIONS] = options

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
        job_resources = {Resource.CPU_TIME: 0.0, Resource.WALL_TIME: 0.0, Resource.MEMORY_USAGE: 0}
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
                    job_resources[Resource.WALL_TIME] = float(line[9:-2])
                elif line.startswith("cputime="):
                    job_resources[Resource.CPU_TIME] = float(line[8:-2])
                elif line.startswith("memory="):
                    job_resources[Resource.MEMORY_USAGE] = float(line[7:-2])
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
            uploader_config = self.config.get(Tool.UPLOADER, {})
            is_upload = uploader_config and uploader_config.get(Tag.UPLOADER_UPLOAD_RESULTS, False)
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
