"""
Launcher implements basic functionality for launching verification tasks.
"""

import datetime
import json
import multiprocessing
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

from components import LOG_FILE, DefaultDir, CloudInfo
from components.component import Component, Tool
from components.coverage_processor import Coverage
from models.tags import Extension, Tag, ComponentName
from models.verification_result import WitnessType, Resource, VerificationResults, Verdict, ADDITIONAL_RESOURCES, \
    Property

TIMESTAMP_PATTERN = "<timestamp>"
RUNDEFINITION_PATTERN = "<rundefinition>"
COMMIT_PATTERN = "<commit>"
DEFAULT_BENCHEXEC_CONTAINER = "--container --full-access-dir /"


class Launcher(Component):
    """
    Main component, which creates verification tasks for the given system,
    launches them and processes results.
    """
    def __init__(self, name: str, config_file: str):
        self.config_file = os.path.basename(config_file).replace(Extension.JSON, "")
        if os.path.exists(config_file):
            with open(config_file, errors='ignore', encoding='ascii') as data_file:
                config = json.load(data_file)
        else:
            config = {
                Tag.DIRS: {
                    Tag.DIRS_RESULTS: DefaultDir.RESULTS,
                    Tag.DIRS_WORK: DefaultDir.WORK
                }
            }

        super().__init__(name, config)

        # Since Launcher does not produce a lot of output and any of its failure is fatal,
        # we can put in on stdout.
        self.debug = self.config.get(Tag.DEBUG, False)
        if self.debug:
            self.output_desc = sys.stdout
        else:
            self.output_desc = subprocess.DEVNULL

        # Remember some useful directories.
        self.root_dir = os.getcwd()  # By default, tool-set is run from this directory.
        self.work_dir = os.path.abspath(self.config.get(Tag.DIRS, {}).get(Tag.DIRS_WORK,
                                                                          DefaultDir.WORK))
        self.results_dir = os.path.abspath(self.config.get(Tag.DIRS, {}).get(Tag.DIRS_RESULTS,
                                                                             DefaultDir.RESULTS))
        if not os.path.exists(self.results_dir):
            os.makedirs(self.results_dir, exist_ok=True)

        if self.config.get(Tag.EXPORT_HTML_ERROR_TRACES, False):
            self.result_dir_et = os.path.abspath(os.path.join(
                self.config[Tag.DIRS][Tag.DIRS_RESULTS], self._get_result_file_prefix()))
        else:
            self.result_dir_et = None
        self.install_dir = os.path.join(self.root_dir, DefaultDir.INSTALL)

        self.cpu_cores = multiprocessing.cpu_count()

        self.backup = None  # File, in which backup copy will be placed during verification.

        # Defines type of scheduler.
        self.scheduler = self.component_config.get(Tag.SCHEDULER)
        self.benchmark_args = self.component_config.get(Tag.BENCHMARK_ARGS, "")
        self.benchexec_options = self.component_config.get(Tag.BENCHEXEC_OPTIONS, DEFAULT_BENCHEXEC_CONTAINER)
        if self.scheduler == CloudInfo.SCHEDULER_CLOUD:
            cloud_master = self.config.get(Tag.CLOUD, {}).get(Tag.CLOUD_MASTER)
            cloud_priority = self.config.get(Tag.CLOUD, {}).get(Tag.CLOUD_PRIORITY,
                                                                CloudInfo.DEFAULT_CLOUD_PRIORITY)
            self.benchmark_args = f"{self.benchmark_args} --cloud --cloudMaster {cloud_master} " \
                                  f"--cloudPriority {cloud_priority}"
        self.job_name_suffix = ""
        self.export_safes = self.config.get(ComponentName.EXPORTER, {}).get(Tag.ADD_VERIFIER_PROOFS, True)

    def __check_result_files(self, file: str, launch_dir: str):
        if file.endswith(".log"):
            dst = LOG_FILE
        else:
            dst = os.path.basename(file)
        if not self.export_safes and WitnessType.CORRECTNESS in file:
            return
        shutil.copy(file, os.path.join(launch_dir, dst))

    def _copy_result_files(self, files: list, group_directory: str) -> str:
        launch_dir = os.path.abspath(tempfile.mkdtemp(dir=group_directory))
        for file in files:
            if os.path.isfile(file):
                self.__check_result_files(file, launch_dir)
            for root, _, files_in in os.walk(file):
                for name in files_in:
                    file = os.path.join(root, name)
                    self.__check_result_files(file, launch_dir)
        return launch_dir

    def _process_coverage(self, result, launch_directory, source_dirs: list,
                          default_source_file=None, work_dir=None):
        cov = Coverage(self, default_source_file=default_source_file)
        cov_queue = multiprocessing.Queue()
        cov_process = multiprocessing.Process(target=cov.compute_coverage,
                                              name=f"coverage_{result.get_name()}",
                                              args=(source_dirs, launch_directory, cov_queue, work_dir))
        cov_process.start()
        cov_process.join()  # Wait since we are already in parallel threads for each launch.
        if not cov_process.exitcode:
            if cov_queue.qsize():
                data = cov_queue.get()
                result.cov_funcs = data.get(Tag.COVERAGE_FUNCS, 0.0)
                result.cov_lines = data.get(Tag.COVERAGE_LINES, 0.0)
                result.coverage_resources[Resource.CPU_TIME] = data.get(Resource.CPU_TIME, 0.0)
                result.coverage_resources[Resource.WALL_TIME] = data.get(Resource.WALL_TIME, 0.0)
                result.coverage_resources[Resource.MEMORY_USAGE] = data.get(Resource.MEMORY_USAGE, 0)
        else:
            warning_msg = f"Coverage was not computed for {result.id} and entry-point "\
                          f"{result.entrypoint}"
            self.logger.warning(warning_msg)

    def _get_from_queue_into_list(self, queue, result_list):
        while not queue.empty():
            launch = queue.get()
            result_list.append(launch)
            if self.backup:
                with open(self.backup, "a", encoding='ascii') as f_report:
                    f_report.write(str(launch) + "\n")
        return result_list

    def _get_result_file_prefix(self):
        return self.config_file + "_" + datetime.datetime.fromtimestamp(time.time()).\
            strftime('%Y_%m_%d_%H_%M_%S')

    def _upload_results(self, uploader_config, result_file):
        server = uploader_config.get(Tag.UPLOADER_SERVER)
        identifier = uploader_config.get(Tag.UPLOADER_IDENTIFIER)
        user = uploader_config.get(Tag.UPLOADER_USER)
        password = uploader_config.get(Tag.UPLOADER_PASSWORD)
        request_sleep = uploader_config.get(Tag.UPLOADER_REQUEST_SLEEP)
        is_parent = uploader_config.get(Tag.UPLOADER_PARENT_ID, False)
        predefined_name = uploader_config.get(Tag.NAME, None)
        if not server:
            self.logger.error("Server was not provided for uploading results, skipping it.")
            return
        if not identifier:
            self.logger.error("Job identifier was not provided for uploading results, skipping it.")
            return
        if not user:
            self.logger.error("User name was not provided for uploading results, skipping it.")
            return
        self.logger.info("Uploading results into server %s with identifier %s", server, identifier)
        uploader = self.get_tool_path(self._get_tool_default_path(Tool.UPLOADER))
        uploader_python_path = os.path.abspath(os.path.join(os.path.dirname(uploader),
                                                            os.path.pardir))
        commits = self.config.get(Tag.COMMITS)
        if commits:
            commit = commits[0]
            res = re.search(r'(\w+)\.\.(\w+)', commit)
            if res:
                commit = res.group(2)
                commits = commit[:7]
        timestamp = datetime.datetime.fromtimestamp(time.time()).strftime('%Y_%m_%d_%H_%M_%S')
        if predefined_name:
            job_name = predefined_name.replace(TIMESTAMP_PATTERN, timestamp)
            job_name = job_name.replace(RUNDEFINITION_PATTERN, self.job_name_suffix)
            job_name = job_name.replace(COMMIT_PATTERN, str(commits))
        elif commits:
            job_name = f"{self.config_file}: {commits} ({timestamp})"
        else:
            job_name = f"{self.config_file} ({timestamp})"
        self.logger.debug("Using name '%s' for uploaded report", job_name)
        command = f"PYTHONPATH={uploader_python_path} {uploader} '{identifier}' " \
                  f"--host='{server}' --username='{user}' --password='{password}' " \
                  f"--archive='{result_file}' --name='{job_name}'"
        self.logger.debug(command)
        if request_sleep:
            command = f"{command} --request-sleep {request_sleep}"
        if is_parent:
            command = f"{command} --copy"
        try:
            subprocess.check_call(command, shell=True)
            self.logger.info("Results were successfully uploaded into the server: %s/jobs", server)
        except Exception as any_exception:
            exception_msg = f"Error on uploading of report archive '{result_file}' "\
                            f"via command '{command}': {any_exception}\n"
            self.logger.warning(exception_msg, exc_info=True)

    @staticmethod
    def _get_none_rule_key(verification_result: VerificationResults):
        return f"{verification_result.id}_{verification_result.entrypoint}"

    def _print_launches_report(self, file_name: str, report_resources: str, results: list,
                               cov_lines: dict = None, cov_funcs: dict = None):
        self.logger.info("Preparing report on launches into file: '%s'", file_name)
        with open(file_name, "w", encoding='ascii') as f_report, \
                open(report_resources, "w", encoding='ascii') as f_resources:
            # Write header.
            f_report.write("Subsystem;Rule;Entrypoint;Verdict;Termination;CPU;Wall;Memory;"
                           "Relevancy;Traces;Filtered traces;Work dir;Cov lines;Cov funcs;"
                           "MEA time\n")
            f_resources.write("Counter;" + ";".join(ADDITIONAL_RESOURCES) + "\n")
            counter = 1
            for result in results:
                # Add coverage information.
                if result.verdict == Verdict.SAFE and not result.rule == Property.COVERAGE:
                    key = self._get_none_rule_key(result)
                    if not result.cov_lines and cov_lines:
                        result.cov_lines = cov_lines.get(key, 0.0)
                    if not result.cov_funcs and cov_funcs:
                        result.cov_funcs = cov_funcs.get(key, 0.0)
                f_report.write(str(result) + "\n")
                f_resources.write(f"{counter};" + result.print_resources() + "\n")
                counter += 1

    def _get_results_names(self) -> tuple:
        reports_prefix = self._get_result_file_prefix()
        report_launches = os.path.join(self.results_dir, f"report_launches_{reports_prefix}.csv")
        result_archive = os.path.join(self.results_dir, f"results_{reports_prefix}.zip")
        report_components = os.path.join(self.results_dir,
                                         f"report_components_{reports_prefix}.csv")
        short_report = os.path.join(self.results_dir, f"short_report_{reports_prefix}.csv")
        report_resources = os.path.join(self.results_dir, f"report_resources_{reports_prefix}.csv")
        return report_launches, result_archive, report_components, short_report, report_resources
