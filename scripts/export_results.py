#!/usr/bin/python3

import argparse
import glob
import json
import logging
import multiprocessing
import re
import resource
import shutil
import subprocess
import tempfile
import time
import zipfile
from filecmp import cmp

from common import *
from component import Component
from config import *

ERROR_TRACE_FILE = "error trace.json"
FINAL_REPORT = "final.json"
CSV_SEPARATOR = ";"
UNKNOWN_DESC_FILE = "problem desc.txt"

TAG_VERSION = "version"
TAG_ADD_VERIFIER_LOGS = "add verifier logs"
TAG_SOURCE_FILES = "source files"

DEFAULT_SOURCES_ARCH = "sources.zip"
SRC_FILES = "src.files"


class Exporter(Component):
    def __init__(self, config, work_dir: str, install_dir: str):
        super(Exporter, self).__init__(COMPONENT_EXPORTER, config)
        self.work_dir = work_dir
        self.install_dir = install_dir

        klever_core_path = self.get_tool_path(DEFAULT_TOOL_PATH[WEB_INTERFACE],
                                              config.get(TAG_TOOLS, {}).get(WEB_INTERFACE))
        sys.path.append(klever_core_path)
        benchexec_path = self.get_tool_path(DEFAULT_TOOL_PATH[BENCHEXEC], config.get(TAG_TOOLS, {}).get(BENCHEXEC))
        sys.path.append(os.path.join(benchexec_path, os.pardir))

        self.version = self.component_config.get(TAG_VERSION)
        self.add_logs = self.component_config.get(TAG_ADD_VERIFIER_LOGS, True)
        self.lock = multiprocessing.Lock()

    def __format_attr(self, name: str, value, compare=False):
        res = {
            "name": name,
            "value": value
        }
        if compare:
            res["compare"] = True
            res["associate"] = True
        return res

    def __create_component_report(self, name, cpu, wall, mem):
        component = dict()
        component['id'] = "/{}".format(name)
        component['parent id'] = "/"
        component['type'] = "component"
        component['name'] = name
        component['resources'] = {
            "CPU time": cpu,
            "memory size": mem,
            "wall time": wall
        }
        component['attrs'] = []
        return component

    def __export_single_trace(self, witness, identifier, rule, report_files_archive_abs, queue: multiprocessing.Queue):

        # noinspection PyUnresolvedReferences
        from core.vrp.et import import_error_trace

        cur_dir = os.getcwd()
        tmp_dir = os.path.abspath(tempfile.mkdtemp(dir=cur_dir))
        os.chdir(tmp_dir)
        witness_processed = 'witness.{}.graphml'.format(identifier)

        # Those messages are waste of space.
        logger = logging.getLogger(name="Klever")
        logger.setLevel(logging.ERROR)
        src = set()

        try:
            shutil.copy(witness, witness_processed)
            trace_json = import_error_trace(logger, witness_processed)
            if not self.debug:
                os.remove(witness_processed)
            src_files = list()
            for src_file in trace_json['files']:
                src_file = os.path.normpath(src_file)
                src_files.append(src_file)
                if os.path.exists(src_file):
                    src.add(src_file)
            trace_json['files'] = src_files

            if rule not in [RULE_RACES] + DEADLOCK_SUB_PROPERTIES:
                self.__process_single_trace(trace_json)
            with open(ERROR_TRACE_FILE, 'w', encoding='utf8') as fp:
                json.dump(trace_json, fp, ensure_ascii=False, sort_keys=True, indent=4)
            with zipfile.ZipFile(report_files_archive_abs, mode='w') as zfp:
                zfp.write(ERROR_TRACE_FILE, arcname="error trace.json")
            if os.path.exists(ERROR_TRACE_FILE) and not self.debug:
                os.remove(ERROR_TRACE_FILE)

            self.logger.debug("Trace {0} has been processed".format(witness))
        except:
            self.logger.warning("Trace {0} is incorrect, skipping it".format(witness), exc_info=True)

        os.chdir(cur_dir)
        if not self.debug:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        utime, stime, memory = resource.getrusage(resource.RUSAGE_SELF)[0:3]
        self.lock.acquire()
        with open(SRC_FILES, "a") as fd:
            for file in src:
                fd.write(file + "\n")
        self.lock.release()
        queue.put({
            TAG_CPU_TIME: float(utime + stime),
            TAG_MEMORY_USAGE: int(memory) * 1024
        })
        sys.exit(0)

    # Add warnings and thread number
    def __process_single_trace(self, parsed_trace: dict):
        is_main_process = False
        is_warn = False
        edge = None
        for edge in parsed_trace['edges']:
            if not is_main_process and 'enter' in edge:
                is_main_process = True
            elif not is_warn and 'warn' in edge:
                    is_warn = True
            if is_main_process:
                edge['thread'] = '1'
            else:
                edge['thread'] = '0'
        if not is_warn and edge:
            edge['warn'] = 'Auto generated error message'

    def __count_resource_usage(self, queue: multiprocessing.Queue):
        iteration_memory = 0
        while not queue.empty():
            resources = queue.get()
            iteration_memory += resources[TAG_MEMORY_USAGE]
            self.cpu_time += round(float(resources[TAG_CPU_TIME]) * 1000)
        self.memory = max(self.memory, iteration_memory)

    def export_traces(self, report_launches: str, report_components: str, archive_name: str, logs=dict()):
        start_wall_time = time.time()
        overall_wall = 0  # Launcher + Exporter.
        overall_cpu = 0  # Sum of all components.
        max_memory = 0

        mea_unsafe_incomplete = 0
        mea_all_unsafes = 0
        mea_overall_initial_traces = 0
        mea_overall_filtered_traces = 0

        main_process_cpu_start = time.process_time()

        reports = []
        max_cores = multiprocessing.cpu_count()

        # Create working directory for Exporter.
        if not os.path.exists(self.work_dir):
            os.makedirs(self.work_dir, exist_ok=True)
        export_dir = os.path.abspath(tempfile.mkdtemp(dir=self.work_dir))
        cur_dir = os.getcwd()
        os.chdir(export_dir)

        # Initialization of root element
        root_element = dict()
        root_element['id'] = "/"
        root_element['parent id'] = None
        root_element['type'] = "component"
        root_element['name'] = "Core"
        root_element['comp'] = [
            {"memory size": str(int(int(subprocess.check_output("free -m", shell=True).splitlines()[1].split()[1]) /
                                    1000)) + "GB"},
            {"node name": subprocess.check_output("uname -n", shell=True).decode().rstrip()},
            {"CPU model": subprocess.check_output("cat /proc/cpuinfo  | grep 'name'| uniq", shell=True).decode().
                replace("model name	: ", "").rstrip()},
            {"CPU cores": str(max_cores)},
            {"Linux kernel version": subprocess.check_output("uname -n", shell=True).decode().rstrip()},
            {"architecture": subprocess.check_output("uname -m", shell=True).decode().rstrip()}
        ]
        root_element['attrs'] = [self.__format_attr(TAG_VERSION, self.version)]

        launcher_id = "/"
        with zipfile.ZipFile(archive_name, mode='w') as final_zip:
            # Components reports.
            with open(report_components, encoding='utf8', errors='ignore') as fp:
                for line in fp.readlines():
                    # Launcher;0.12;203.77;12365824
                    res = re.search(r'(\w+){0}(.+){0}(.+){0}(.+)'.format(CSV_SEPARATOR), line)
                    if res:
                        name = res.group(1)
                        if name == "Name":
                            continue
                        cpu = int(float(res.group(2)) * 1000)
                        wall = int(float(res.group(3)) * 1000)
                        mem = int(float(res.group(4)))
                        new_report = self.__create_component_report(name, cpu, wall, mem)
                        if name in logs:
                            stored_logs = []
                            counter = 0
                            for log in logs[name]:
                                is_cached = False
                                for stored_log in stored_logs:
                                    if cmp(stored_log, log):
                                        is_cached = True
                                if is_cached:
                                    continue
                                else:
                                    stored_logs.append(log)
                                unknown_report = dict()
                                unknown_report['id'] = "{}/unknown/{}".format(new_report['id'], counter)
                                unknown_report['parent id'] = "{}".format(new_report['id'])
                                unknown_report['type'] = "unknown"
                                unknown_archive = "unknown_{}_{}.zip".format(name, counter)
                                counter += 1
                                with zipfile.ZipFile(unknown_archive, mode='w') as zfp:
                                    zfp.write(log, arcname=UNKNOWN_DESC_FILE)
                                final_zip.write(unknown_archive, arcname=unknown_archive)
                                unknown_report["problem desc"] = unknown_archive
                                reports.append(unknown_report)
                        reports.append(new_report)
                        if name == COMPONENT_LAUNCHER:
                            launcher_id += name
                            overall_wall += wall
                        overall_cpu += cpu
                        max_memory = max(max_memory, mem)

            trace_counter = 0
            verifier_counter = 0

            unknowns = {}  # cache of unknowns to prevent duplicating reports.
            unsafes = []  # archives with error traces.

            # Process several error traces in parallel.
            process_pool = []
            queue = multiprocessing.Queue()
            for i in range(max_cores):
                process_pool.append(None)
            with open(report_launches, encoding='utf8', errors='ignore') as fp:
                for line in fp.readlines():
                    # <subsystem>;<rule id>;<entrypoint>;<verdict>;<termination reason>;<CPU (s)>;<wall (s)>;
                    # memory (Mb);<relevancy>;<number of traces>;<number of filtered traces>;<work dir>;<cov lines>;
                    # <cov funcs>;<CPU (s) for filtering>
                    res = re.search(r'(.+){0}(.+){0}(.+){0}(\w+){0}(.+){0}'
                                    r'(\d+){0}(\d+){0}(\d+){0}(\w+){0}(\d+){0}(\d+){0}'
                                    r'(.+){0}(.+){0}(.+){0}(.+)'.format(CSV_SEPARATOR), line)
                    if res:
                        subsystem = res.group(1)
                        rule = res.group(2)
                        if rule == RULE_COVERAGE:
                            continue
                        entrypoint = res.group(3)
                        if entrypoint.endswith(ENTRY_POINT_SUFFIX):
                            entrypoint = entrypoint[:-len(ENTRY_POINT_SUFFIX)]
                        if entrypoint.endswith(STATIC_SUFFIX):
                            entrypoint = entrypoint[:-len(STATIC_SUFFIX)]
                        verdict = res.group(4)
                        if verdict == VERDICT_UNSAFE:
                            mea_all_unsafes += 1
                        termination_reason = res.group(5)
                        if not termination_reason == TERMINATION_SUCCESS and verdict == VERDICT_UNSAFE:
                            mea_unsafe_incomplete += 1
                            incomplete_result = True
                        else:
                            incomplete_result = False
                        cpu = int(res.group(6)) * 1000
                        wall = int(res.group(7)) * 1000
                        mem = int(res.group(8)) * 1000000
                        relevancy = res.group(9)
                        et = int(res.group(10))
                        mea_overall_initial_traces += et
                        filtered = int(res.group(11))
                        mea_overall_filtered_traces += filtered
                        work_dir = res.group(12)
                        cov_lines = float(res.group(13))
                        cov_funcs = float(res.group(14))
                        filter_cpu = round(float(res.group(15)), 2)

                        verification_element = dict()
                        verification_element['id'] = "/CPAchecker_{}".format(verifier_counter)
                        verification_element['parent id'] = launcher_id
                        verification_element['type'] = "verification"
                        verification_element['name'] = "CPAchecker"
                        attrs = list()
                        attrs.append(self.__format_attr("Subsystem", subsystem, True))
                        attrs.append(self.__format_attr("Verification object", entrypoint, True))
                        attrs.append(self.__format_attr("Rule specification", rule, True))
                        verification_element['attrs'] = attrs
                        verification_element['resources'] = {
                            "CPU time": cpu,
                            "memory size": mem,
                            "wall time": wall
                        }
                        overall_cpu += cpu
                        max_memory = max(max_memory, mem)
                        reports.append(verification_element)
                        witnesses = glob.glob("{}/*.graphml".format(work_dir))
                        for witness in witnesses:
                            unsafe_element = {}
                            unsafe_element['parent id'] = "/CPAchecker_{}".format(verifier_counter)
                            unsafe_element['type'] = "unsafe"
                            attrs = [
                                self.__format_attr("Traces", [
                                    self.__format_attr("Filtered", str(filtered)),
                                    self.__format_attr("Initial", str(et))
                                ]),
                                self.__format_attr("Found all traces", str(not incomplete_result)),
                                self.__format_attr("Filtering time", str(filter_cpu))
                            ]
                            m = re.search(r'witness\.(.*)\.graphml', witness)
                            identifier = m.group(1)

                            archive_id = "unsafe_{}".format(trace_counter)
                            trace_counter += 1
                            report_files_archive = archive_id + ".zip"
                            report_files_archive_abs = os.path.abspath(report_files_archive)

                            try:
                                while True:
                                    for i in range(max_cores):
                                        if process_pool[i] and not process_pool[i].is_alive():
                                            process_pool[i].join()
                                            process_pool[i] = None
                                        if not process_pool[i]:
                                            process_pool[i] = multiprocessing.Process(target=self.__export_single_trace,
                                                                                      name=witness,
                                                                                      args=(witness, identifier, rule,
                                                                                            report_files_archive_abs,
                                                                                            queue))
                                            process_pool[i].start()
                                            raise NestedLoop
                                    time.sleep(BUSY_WAITING_INTERVAL)
                                    self.__count_resource_usage(queue)
                            except NestedLoop:
                                pass
                            except:
                                self.logger.error("Could not export results:", exc_info=True)
                                kill_launches(process_pool)

                            unsafe_element['id'] = "/CPAchecker/" + archive_id
                            unsafe_element['attrs'] = attrs
                            unsafe_element['error traces'] = [report_files_archive]
                            unsafe_element['sources'] = DEFAULT_SOURCES_ARCH
                            reports.append(unsafe_element)
                            unsafes.append(report_files_archive_abs)

                        if not witnesses or incomplete_result:
                            other_element = dict()
                            if verdict == VERDICT_SAFE:
                                verdict = "safe"
                                attrs = [
                                    self.__format_attr("Coverage", [
                                        self.__format_attr("Lines", "{0}%".format(cov_lines)),
                                        self.__format_attr("Functions", "{0}%".format(cov_funcs))
                                    ])
                                ]
                                # TODO: how to determine relevancy there?
                                if rule not in [RULE_RACES] + DEADLOCK_SUB_PROPERTIES:
                                    attrs.append(self.__format_attr("Relevancy", relevancy))
                            else:
                                if rule == RULE_TERMINATION and verdict == VERDICT_UNSAFE:
                                    text = "Program never terminates"
                                else:
                                    text = termination_reason
                                attrs = []
                                verdict = "unknown"

                                if self.add_logs:
                                    is_cached = False
                                    identifier = str(verifier_counter)
                                else:
                                    if text in unknowns or not self.add_logs:
                                        identifier = unknowns[text]
                                        is_cached = True
                                    else:
                                        identifier = str(verifier_counter)
                                        unknowns[text] = identifier
                                        is_cached = False

                                unknown_archive = "unknown_{}.zip".format(identifier)
                                other_element["problem desc"] = unknown_archive

                                if not is_cached:
                                    with zipfile.ZipFile(unknown_archive, mode='w') as zfp:
                                        with open(UNKNOWN_DESC_FILE, 'w') as fp, \
                                                open(os.path.join(work_dir, "log.txt")) as f_log:
                                            fp.write("Termination reason: {}\n".format(text))
                                            if incomplete_result:
                                                fp.write("Unsafe-incomplete\n")
                                            if self.add_logs:
                                                for line in f_log.readlines():
                                                    fp.write(line)
                                        zfp.write(UNKNOWN_DESC_FILE, arcname=UNKNOWN_DESC_FILE)
                                    if os.path.exists(UNKNOWN_DESC_FILE):
                                        os.remove(UNKNOWN_DESC_FILE)
                                    final_zip.write(unknown_archive, arcname=unknown_archive)
                                    if os.path.exists(unknown_archive):
                                        os.remove(unknown_archive)

                            other_element['parent id'] = "/CPAchecker_{}".format(verifier_counter)
                            other_element['type'] = verdict
                            other_element['id'] = "/CPAchecker/other_" + str(verifier_counter)
                            other_element['attrs'] = attrs
                            reports.append(other_element)

                        verifier_counter += 1

                wait_for_launches(process_pool)

                failed_reports = 0
                for unsafe in unsafes:
                    base_name = os.path.basename(unsafe)
                    if os.path.exists(unsafe):
                        final_zip.write(unsafe, arcname=base_name)
                        os.remove(unsafe)
                    else:
                        # delete corresponding record.
                        for report in reports:
                            if report.get("type") == "unsafe" and report.get("error traces")[0] == base_name:
                                reports.remove(report)
                                failed_reports += 1
                                break

                for report in reports:
                    if report.get("type") == "component" and report.get("name") == COMPONENT_MEA:
                        percent_of_unsafe_incomplete = 0
                        if mea_all_unsafes != 0:
                            percent_of_unsafe_incomplete = round(100 * mea_unsafe_incomplete / mea_all_unsafes, 2)

                        report["attrs"].append(self.__format_attr("Unsafes", str(mea_all_unsafes)))
                        report["attrs"].append(self.__format_attr("Unsafe-incomplete",
                                                                  str(percent_of_unsafe_incomplete) + "%"))
                        report["attrs"].append(self.__format_attr("Initial traces", str(mea_overall_initial_traces)))
                        report["attrs"].append(self.__format_attr("Filtered traces", str(mea_overall_filtered_traces)))
                        break

                self.__count_resource_usage(queue)
                if failed_reports:
                    self.logger.warning("Failed error traces: {0} of {1}".format(failed_reports, len(unsafes)))
                self.memory += int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024
                exporter_wall_time = round((time.time() - start_wall_time) * 1000)
                overall_wall += exporter_wall_time
                self.cpu_time += round(float((time.process_time() - main_process_cpu_start)) * 1000)
                overall_cpu += self.cpu_time
                reports.append(self.__create_component_report(COMPONENT_EXPORTER, self.cpu_time,
                                                              exporter_wall_time, self.memory))
                self.get_component_full_stats()

                root_element['resources'] = {
                    "CPU time": overall_cpu,
                    "memory size": max_memory,
                    "wall time": overall_wall
                }
                reports.append(root_element)
                src = set()
                if os.path.exists(SRC_FILES):
                    with open(SRC_FILES, "r") as fd:
                        for line in fd.readlines():
                            line = line.rstrip()
                            src.add(os.path.normpath(line))
                    with zipfile.ZipFile(DEFAULT_SOURCES_ARCH, mode='w') as zfp:
                        for src_file in src:
                            zfp.write(src_file)
                    final_zip.write(DEFAULT_SOURCES_ARCH)

                with open(FINAL_REPORT, 'w', encoding='utf8') as f_results:
                    json.dump(reports, f_results, ensure_ascii=False, sort_keys=True, indent=4)
                final_zip.write(FINAL_REPORT, arcname="reports.json")
                os.remove(FINAL_REPORT)

        os.chdir(cur_dir)
        if not self.debug:
            shutil.rmtree(export_dir, ignore_errors=True)
        self.logger.info("Exporting results has been completed")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", metavar="PATH", help="set PATH to configuration", required=True)
    options = parser.parse_args()
    with open(options.config) as data_file:
        config = json.load(data_file)

    install_dir = os.path.abspath(DEFAULT_INSTALL_DIR)
    results_dir = os.path.abspath(config[TAG_DIRS][TAG_DIRS_RESULTS])
    work_dir = os.path.abspath(os.path.join(config[TAG_DIRS][TAG_DIRS_WORK], DEFAULT_EXPORT_DIR))

    exporter = Exporter(config, work_dir, install_dir)

    timestamp = config.get(COMPONENT_EXPORTER, {}).get("timestamp")
    if not timestamp:
        sys.exit("Timestamp for report was not specified")
    report_launches = os.path.join(results_dir, "report_launches_{}.csv".format(timestamp))
    report_components = os.path.join(results_dir, "report_components_{}.csv".format(timestamp))
    archive = os.path.join(results_dir, "results_{}.zip".format(timestamp))
    exporter.export_traces(report_launches, report_components, archive)
