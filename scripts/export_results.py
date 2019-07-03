#!/usr/bin/python3

import argparse
import glob
import json
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


class Exporter(Component):
    def __init__(self, config, work_dir: str, install_dir: str):
        super(Exporter, self).__init__(COMPONENT_EXPORTER, config)
        self.work_dir = work_dir
        self.install_dir = install_dir
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

    def export_traces(self, report_launches: str, report_components: str, archive_name: str, unknown_desc: dict = dict):
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
                        if name in unknown_desc:
                            counter = 0
                            for u_desc in unknown_desc[name]:
                                log = u_desc[TAG_LOG_FILE]
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
                                unknown_report['attrs'] = u_desc.get(TAG_ATTRS)
                                unknown_report['resources'] = {
                                    "CPU time": u_desc[TAG_CPU_TIME],
                                    "memory size": u_desc[TAG_MEMORY_USAGE],
                                    "wall time": u_desc[TAG_WALL_TIME]
                                }
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
            unsafes = {}  # archives with error traces.

            # Process several error traces in parallel.
            source_files = set()
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
                        witnesses = glob.glob("{}/witness.*{}".format(work_dir, ARCHIVE_EXTENSION))
                        for witness in witnesses:
                            unsafe_element = {}
                            unsafe_element['parent id'] = "/CPAchecker_{}".format(verifier_counter)
                            unsafe_element['type'] = "unsafe"
                            found_all_traces = not incomplete_result
                            if rule == RULE_RACES:
                                found_all_traces = True
                            attrs = [
                                self.__format_attr("Traces", [
                                    self.__format_attr("Filtered", str(filtered)),
                                    self.__format_attr("Initial", str(et))
                                ]),
                                self.__format_attr("Found all traces", str(found_all_traces)),
                                self.__format_attr("Filtering time", str(filter_cpu)),
                                self.__format_attr("Coverage", [
                                    self.__format_attr("Lines", "{0}".format(cov_lines)),
                                    self.__format_attr("Functions", "{0}".format(cov_funcs))
                                ])
                            ]

                            archive_id = "unsafe_{}".format(trace_counter)
                            trace_counter += 1
                            report_files_archive = archive_id + ".zip"

                            unsafe_element['id'] = "/CPAchecker/" + archive_id
                            unsafe_element['attrs'] = attrs
                            unsafe_element['error traces'] = [report_files_archive]
                            unsafe_element['sources'] = DEFAULT_SOURCES_ARCH
                            reports.append(unsafe_element)
                            unsafes[report_files_archive] = witness

                            try:
                                src = json.loads(zipfile.ZipFile(witness, 'r').read(ERROR_TRACE_SOURCES).decode())
                                source_files.update(src)
                            except:
                                self.logger.warning("Cannot process sources: ", exc_info=True)

                        if not witnesses or incomplete_result:
                            other_element = dict()
                            if verdict == VERDICT_SAFE:
                                verdict = "safe"
                                attrs = [
                                    self.__format_attr("Coverage", [
                                        self.__format_attr("Lines", "{0}".format(cov_lines)),
                                        self.__format_attr("Functions", "{0}".format(cov_funcs))
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
                                attrs = [
                                    self.__format_attr("Coverage", [
                                        self.__format_attr("Lines", "{0}".format(cov_lines)),
                                        self.__format_attr("Functions", "{0}".format(cov_funcs))
                                    ])
                                ]
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

                failed_reports = 0
                for base_name, abs_path in unsafes.items():
                    if os.path.exists(abs_path):
                        final_zip.write(abs_path, arcname=base_name)
                        os.remove(abs_path)
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
                with zipfile.ZipFile(DEFAULT_SOURCES_ARCH, mode='w') as zfp:
                    for src_file in source_files:
                        zfp.write(src_file)
                final_zip.write(DEFAULT_SOURCES_ARCH)
                os.remove(DEFAULT_SOURCES_ARCH)

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
