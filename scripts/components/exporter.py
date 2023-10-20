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
Component for extracting results into archive to be uploaded in the web-interface.
"""

import multiprocessing
import resource
import subprocess
import tempfile
import zipfile

from components.component import Component
from components.coverage_processor import extract_internal_coverage, write_coverage, merge_coverages
from models.verification_result import *

ERROR_TRACE_FILE = "error trace.json"
FINAL_REPORT = "final.json"
CSV_SEPARATOR = ";"
UNKNOWN_DESC_FILE = "problem desc.txt"

TAG_VERSION = "version"
TAG_ADD_VERIFIER_LOGS = "add verifier logs"
TAG_SOURCE_FILES = "source files"

DEFAULT_SOURCES_ARCH = "sources.zip"

GLOBAL_COVERAGE_MAX = "max"
GLOBAL_COVERAGE_REAL = "real"


class Exporter(Component):
    """
    Component for extracting results into archive to be uploaded in the web-interface.
    """
    def __init__(self, config, work_dir: str, install_dir: str,
                 properties_desc=PropertiesDescription(), tool=DEFAULT_VERIFIER_TOOL):
        super().__init__(COMPONENT_EXPORTER, config)
        self.work_dir = work_dir
        self.install_dir = install_dir
        self.version = self.component_config.get(TAG_VERSION)
        self.add_logs = self.component_config.get(TAG_ADD_VERIFIER_LOGS, True)
        self.add_proofs = self.component_config.get(TAG_ADD_VERIFIER_PROOFS, True)
        self.lock = multiprocessing.Lock()
        self.global_coverage_element = {}
        self.tool = tool
        self.properties_desc = properties_desc

    @staticmethod
    def __format_attr(name: str, value, compare=False):
        if isinstance(value, int):
            value = str(value)
        res = {
            "name": name,
            "value": value
        }
        if compare:
            res["compare"] = True
            res["associate"] = True
        return res

    @staticmethod
    def __create_component_report(name, cpu, wall, mem):
        component = {'id': f"/{name}", 'parent id': "/", 'type': "component", 'name': name,
                     'resources': {
                         "CPU time": cpu,
                         "memory size": mem,
                         "wall time": wall
                     }, 'attrs': []}
        return component

    @staticmethod
    def __process_coverage(final_zip: zipfile.ZipFile, verifier_counter: int, work_dir: str,
                           coverage_sources: dict, ignore=False) -> str:
        cov_name = None
        coverage = os.path.join(os.path.join(work_dir, DEFAULT_COVERAGE_ARCH))
        if os.path.exists(coverage):
            if not ignore:
                cov_name = f"coverage_{verifier_counter}.zip"
                final_zip.write(coverage, arcname=cov_name)

            coverage_src = os.path.join(os.path.join(work_dir, DEFAULT_COVERAGE_SOURCE_FILES))
            if os.path.exists(coverage_src):
                with open(coverage_src, encoding='utf8') as f_s:
                    for line_src in f_s.readlines():
                        # pylint: disable=consider-using-f-string
                        res = re.search(r'^(.+){0}(.+)$'.format(CSV_SEPARATOR), line_src)
                        if res:
                            coverage_sources[res.group(1)] = res.group(2)
        return cov_name

    def __print_coverage(self, final_zip: zipfile.ZipFile, counter: int, function_coverage: dict,
                         line_coverage: dict, stats: dict, cov_type: str):
        cov_name = f"gc_{counter}.zip"
        if not function_coverage or not line_coverage:
            return
        final_zip.write(write_coverage(counter, function_coverage, line_coverage, stats),
                        arcname=cov_name)
        if not self.global_coverage_element:
            self.global_coverage_element = {
                "id": "/",
                "parent id": None,
                "type": "job coverage",
                "name": "Global coverage",
                "coverage": {}
            }
        self.global_coverage_element["coverage"][cov_type] = cov_name

    def __process_specific_coverage(self, work_dirs: list, cov_type: str,
                                    final_zip: zipfile.ZipFile, counter: int,
                                    coverage_by_rule: dict, is_rule=False):
        function_coverage = {}
        line_coverage = {}
        stats = {}
        for work_dir in work_dirs:
            coverage = os.path.join(os.path.join(work_dir, DEFAULT_COVERAGE_ARCH))
            if os.path.exists(coverage):
                with zipfile.ZipFile(coverage) as tmp_arch:
                    data = json.loads(tmp_arch.read(DEFAULT_COVERAGE_FILE).
                                      decode('utf8', errors='ignore'))
                    extract_internal_coverage(data, function_coverage, line_coverage, stats)
        if is_rule:
            for merge_type, results in coverage_by_rule.items():
                if not results[TAG_STATISTICS]:
                    results[TAG_STATISTICS] = stats
                merge_coverages(function_coverage, results[TAG_FUNCTION_COVERAGE],
                                line_coverage, results[TAG_LINE_COVERAGE], merge_type)
        self.__print_coverage(final_zip, counter, function_coverage, line_coverage, stats, cov_type)
        return counter + 1

    def __process_global_coverage(self, global_cov_files: dict, final_zip: zipfile.ZipFile):
        counter = 0
        coverage_by_rule = {
            COVERAGE_MERGE_TYPE_UNION: {},
            COVERAGE_MERGE_TYPE_INTERSECTION: {}
        }
        for _, description in coverage_by_rule.items():
            description[TAG_FUNCTION_COVERAGE] = {}
            description[TAG_LINE_COVERAGE] = {}
            description[TAG_STATISTICS] = {}
        for cov_type, work_dirs in global_cov_files.items():
            if not work_dirs:
                continue
            if cov_type == GLOBAL_COVERAGE_REAL:
                for rule, work_dirs_by_rule in work_dirs.items():
                    counter = self.__process_specific_coverage(work_dirs_by_rule, rule, final_zip,
                                                               counter, coverage_by_rule, True)

            else:
                counter = self.__process_specific_coverage(work_dirs, cov_type, final_zip, counter,
                                                           coverage_by_rule)
        for merge_type, results in coverage_by_rule.items():
            self.__print_coverage(final_zip, counter, results[TAG_FUNCTION_COVERAGE],
                                  results[TAG_LINE_COVERAGE], results[TAG_STATISTICS], merge_type)
            counter += 1

    def export(self, report_launches: str, report_resources: str, report_components: str,
               archive_name: str, unknown_desc=None, component_attrs=None, verifier_config=None):
        """
        Main method for extracting results into archive to be uploaded in the web-interface.
        """
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
        root_element = {'id': "/", 'parent id': None, 'type': "component", 'name': "Core", 'comp': [
            {"memory size": str(int(int(subprocess.check_output("free -m", shell=True).
                                        splitlines()[1].split()[1]) / 1000)) + "GB"},
            {"node name": subprocess.check_output("uname -n", shell=True).decode().rstrip()},
            {"CPU model": subprocess.check_output("cat /proc/cpuinfo  | grep 'name'| uniq",
                                                  shell=True).decode().
                replace("model name	: ", "").rstrip()},
            {"CPU cores": str(max_cores)},
            {"Linux kernel version": subprocess.check_output("uname -r", shell=True).
                decode().rstrip()},
            {"architecture": subprocess.check_output("uname -m", shell=True).decode().rstrip()}
        ]}
        if verifier_config:
            root_element['config'] = verifier_config
        if self.version:
            root_element['attrs'] = [self.__format_attr(TAG_VERSION, self.version)]
        else:
            root_element['attrs'] = []

        launcher_id = "/"
        if_coverage_sources_written = False
        coverage_sources = {}
        global_cov_files = {
            GLOBAL_COVERAGE_MAX: set(),
            GLOBAL_COVERAGE_REAL: {}
        }
        with zipfile.ZipFile(archive_name, mode='w', compression=zipfile.ZIP_DEFLATED) as final_zip:
            # Components reports.
            with open(report_components, encoding='utf8', errors='ignore') as file_obj:
                for line in file_obj.readlines():
                    # pylint: disable=consider-using-f-string
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
                        if unknown_desc and name in unknown_desc:
                            counter = 0
                            for u_desc in unknown_desc[name]:
                                log = u_desc[TAG_LOG_FILE]
                                unknown_report = {'id': f"{new_report['id']}/unknown/{counter}",
                                                  'parent id': f"{new_report['id']}",
                                                  'type': "unknown"}
                                unknown_archive = f"unknown_{name}_{counter}.zip"
                                counter += 1
                                with zipfile.ZipFile(unknown_archive, mode='w',
                                                     compression=zipfile.ZIP_DEFLATED) as arch_obj:
                                    arch_obj.write(log, arcname=UNKNOWN_DESC_FILE)
                                final_zip.write(unknown_archive, arcname=unknown_archive)
                                unknown_report["problem desc"] = unknown_archive
                                unknown_report['attrs'] = u_desc.get(TAG_ATTRS)
                                unknown_report['resources'] = {
                                    "CPU time": u_desc[TAG_CPU_TIME],
                                    "memory size": u_desc[TAG_MEMORY_USAGE],
                                    "wall time": u_desc[TAG_WALL_TIME]
                                }
                                reports.append(unknown_report)
                        if component_attrs and name in component_attrs:
                            new_report['attrs'] = component_attrs[name]
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
            proofs = {}

            # Process several error traces in parallel.
            source_files = {}
            with open(report_launches, encoding='utf8', errors='ignore') as file_obj, \
                    open(report_resources, encoding='utf8', errors='ignore') as res_obj:
                resources_data = res_obj.readlines()[1:]
                id_counter = 0
                for line in file_obj.readlines():
                    # <subsystem>;<rule id>;<entrypoint>;<verdict>;<termination reason>;<CPU (s)>;
                    # <wall (s)>;memory (Mb);<relevancy>;<number of traces>;
                    # <number of filtered traces>;<work dir>;<cov lines>;
                    # <cov funcs>;<CPU (s) for filtering>
                    # pylint: disable=consider-using-f-string
                    res = re.search(r'(.+){0}(.+){0}(.+){0}(\w+){0}(.+){0}'
                                    r'(.+){0}(.+){0}(\d+){0}(\w+){0}(\d+){0}(\d+){0}'
                                    r'(.+){0}(.+){0}(.+){0}(.+)'.format(CSV_SEPARATOR), line)
                    if res:
                        subsystem = res.group(1)
                        rule = res.group(2)
                        entrypoint = res.group(3)
                        if entrypoint.endswith(ENTRY_POINT_SUFFIX):
                            entrypoint = entrypoint[:-len(ENTRY_POINT_SUFFIX)]
                        if entrypoint.endswith(STATIC_SUFFIX):
                            entrypoint = entrypoint[:-len(STATIC_SUFFIX)]
                        verdict = res.group(4)
                        if verdict == VERDICT_UNSAFE:
                            mea_all_unsafes += 1
                        termination_reason = res.group(5)
                        if not termination_reason == TERMINATION_SUCCESS and \
                                verdict == VERDICT_UNSAFE:
                            mea_unsafe_incomplete += 1
                            incomplete_result = True
                        else:
                            incomplete_result = False
                        cpu = float(res.group(6)) * 1000
                        wall = float(res.group(7)) * 1000
                        mem = int(res.group(8)) * 1000000
                        relevancy = res.group(9)
                        et_num = int(res.group(10))
                        mea_overall_initial_traces += et_num
                        filtered = int(res.group(11))
                        mea_overall_filtered_traces += filtered
                        work_dir = res.group(12)
                        cov_lines = float(res.group(13))
                        cov_funcs = float(res.group(14))
                        filter_cpu = round(float(res.group(15)), 2)

                        verification_element = {'id': f"/{self.tool}_{verifier_counter}",
                                                'parent id': launcher_id, 'type': "verification",
                                                'name': self.tool}
                        attrs = []
                        if subsystem and subsystem != ".":
                            attrs.append(self.__format_attr("Subsystem", subsystem, True))
                        attrs.append(self.__format_attr("Verification object", entrypoint, True))
                        attrs.append(self.__format_attr("Rule specification", rule, True))
                        verification_element['attrs'] = attrs
                        verification_element['resources'] = {
                            "CPU time": cpu,
                            "memory size": mem,
                            "wall time": wall
                        }
                        res_data = resources_data[id_counter].rstrip().split(CSV_SEPARATOR)
                        for i, add_res in enumerate(ADDITIONAL_RESOURCES):
                            verification_element['resources'][add_res] = res_data[i + 1]
                        id_counter += 1
                        if rule == PROPERTY_COVERAGE:
                            global_cov_files[GLOBAL_COVERAGE_MAX].add(work_dir)
                            self.__process_coverage(final_zip, verifier_counter, work_dir,
                                                    coverage_sources, True)
                            if not if_coverage_sources_written:
                                verification_element['coverage sources'] = \
                                    DEFAULT_COVERAGE_SOURCES_ARCH
                                if_coverage_sources_written = True
                            reports.append(verification_element)
                            verifier_counter += 1
                            continue
                        cov_name = self.__process_coverage(final_zip, verifier_counter, work_dir,
                                                           coverage_sources)
                        if cov_name:
                            if rule not in global_cov_files[GLOBAL_COVERAGE_REAL]:
                                global_cov_files[GLOBAL_COVERAGE_REAL][rule] = set()
                            global_cov_files[GLOBAL_COVERAGE_REAL][rule].add(work_dir)
                            verification_element['coverage'] = cov_name
                            if not if_coverage_sources_written:
                                verification_element['coverage sources'] = \
                                    DEFAULT_COVERAGE_SOURCES_ARCH
                                if_coverage_sources_written = True

                        overall_cpu += cpu
                        max_memory = max(max_memory, mem)
                        reports.append(verification_element)
                        witnesses = glob.glob(
                            f"{work_dir}/{WITNESS_VIOLATION}_witness*{ARCHIVE_EXTENSION}")
                        for witness in witnesses:
                            unsafe_element = {
                                'parent id': f"/{self.tool}_{verifier_counter}",
                                'type': "unsafe"
                            }
                            found_all_traces = not incomplete_result
                            if self.properties_desc.get_property_arg(
                                    rule, PROPERTY_IS_ALL_TRACES_FOUND, ignore_missing=True):
                                # Ignore verdict and termination reason for determining
                                # if all traces were found.
                                found_all_traces = True
                            attrs = [
                                self.__format_attr("Traces", [
                                    self.__format_attr("Filtered", str(filtered)),
                                    self.__format_attr("Initial", str(et_num))
                                ]),
                                self.__format_attr("Found all traces", str(found_all_traces)),
                                self.__format_attr("Filtering time", str(filter_cpu)),
                                self.__format_attr("Coverage", [
                                    self.__format_attr("Lines", f"{cov_lines}"),
                                    self.__format_attr("Functions", f"{cov_funcs}")
                                ])
                            ]

                            archive_id = f"unsafe_{trace_counter}"
                            trace_counter += 1
                            report_files_archive = archive_id + ".zip"

                            unsafe_element['id'] = f"/{self.tool}/{archive_id}"
                            unsafe_element['attrs'] = attrs
                            unsafe_element['error traces'] = [report_files_archive]
                            unsafe_element['sources'] = DEFAULT_SOURCES_ARCH
                            reports.append(unsafe_element)
                            unsafes[report_files_archive] = witness

                            try:
                                with zipfile.ZipFile(witness, 'r') as arc_arch:
                                    src = json.loads(arc_arch.read(ERROR_TRACE_SOURCES).
                                                     decode('utf8', errors='ignore'))
                                for src_file, src_file_res in src:
                                    source_files[src_file] = src_file_res
                            except Exception as exception:
                                self.logger.warning(f"Cannot process sources: {exception}\n",
                                                    exc_info=True)

                        if not witnesses or incomplete_result:
                            other_element = {}
                            witnesses = glob.glob(
                                f"{work_dir}/{WITNESS_CORRECTNESS}_witness*{ARCHIVE_EXTENSION}")
                            if verdict == VERDICT_SAFE:
                                verdict = "safe"
                                if witnesses and self.add_proofs:
                                    # TODO: only one correctness witness is supported.
                                    if len(witnesses) > 1:
                                        self.logger.warning(
                                            "Only one correctness witness is supported per "
                                            "verification task")
                                    witness = witnesses[0]

                                    archive_id = f"safe_{trace_counter}"
                                    trace_counter += 1
                                    report_files_archive = archive_id + ".zip"

                                    other_element['proof'] = report_files_archive
                                    other_element['sources'] = DEFAULT_SOURCES_ARCH
                                    proofs[report_files_archive] = witness

                                    try:
                                        with zipfile.ZipFile(witness, 'r') as arc_arch:
                                            src = json.loads(arc_arch.read(ERROR_TRACE_SOURCES).
                                                             decode('utf8', errors='ignore'))
                                        for src_file, src_file_res in src:
                                            source_files[src_file] = src_file_res
                                    except Exception as exception:
                                        self.logger.warning(f"Cannot process sources: "
                                                            f"{exception}\n", exc_info=True)

                                attrs = [
                                    self.__format_attr("Coverage", [
                                        self.__format_attr("Lines", f"{cov_lines}"),
                                        self.__format_attr("Functions", f"{cov_funcs}")
                                    ])
                                ]
                                if self.properties_desc.get_property_arg(rule,
                                                                         PROPERTY_IS_RELEVANCE,
                                                                         ignore_missing=True):
                                    # If we do not have information about relevancy in output.
                                    attrs.append(self.__format_attr("Relevancy", relevancy))
                            else:
                                attrs = [
                                    self.__format_attr("Coverage", [
                                        self.__format_attr("Lines", f"{cov_lines}"),
                                        self.__format_attr("Functions", f"{cov_funcs}")
                                    ])
                                ]
                                verdict = "unknown"

                                if self.add_logs:
                                    is_cached = False
                                    identifier = str(verifier_counter)
                                else:
                                    if termination_reason in unknowns or not self.add_logs:
                                        identifier = unknowns[termination_reason]
                                        is_cached = True
                                    else:
                                        identifier = str(verifier_counter)
                                        unknowns[termination_reason] = identifier
                                        is_cached = False

                                unknown_archive = f"unknown_{identifier}.zip"
                                other_element["problem desc"] = unknown_archive

                                if not is_cached:
                                    with zipfile.ZipFile(unknown_archive, mode='w',
                                                         compression=zipfile.ZIP_DEFLATED) \
                                            as arch_obj:
                                        with open(UNKNOWN_DESC_FILE, 'w', encoding='utf8') \
                                                as unk_obj:
                                            unk_obj.write(f"Termination reason: "
                                                          f"{termination_reason}\n")
                                            if incomplete_result:
                                                unk_obj.write("Unsafe-incomplete\n")
                                            if self.add_logs:
                                                log_name = os.path.join(work_dir, "log.txt")
                                                if os.path.exists(log_name):
                                                    with open(log_name, encoding='utf8') as f_log:
                                                        for log_line in f_log.readlines():
                                                            unk_obj.write(log_line)
                                                else:
                                                    self.logger.warning(
                                                        f"Log file '{log_name}' does not exist")
                                        arch_obj.write(UNKNOWN_DESC_FILE, arcname=UNKNOWN_DESC_FILE)
                                    if os.path.exists(UNKNOWN_DESC_FILE):
                                        os.remove(UNKNOWN_DESC_FILE)
                                    final_zip.write(unknown_archive, arcname=unknown_archive)
                                    if os.path.exists(unknown_archive):
                                        os.remove(unknown_archive)

                            other_element['parent id'] = f"/{self.tool}_{verifier_counter}"
                            other_element['type'] = verdict
                            other_element['id'] = f"/{self.tool}/other_{verifier_counter}"
                            other_element['attrs'] = attrs
                            reports.append(other_element)

                        verifier_counter += 1

                failed_reports = set()
                for base_name, abs_path in unsafes.items():
                    if os.path.exists(abs_path):
                        final_zip.write(abs_path, arcname=base_name)
                        os.remove(abs_path)
                    else:
                        # delete corresponding record.
                        for report in reports:
                            if report.get("type") == "unsafe" and \
                                    report.get("error traces")[0] == base_name:
                                failed_reports.add(report)
                                break

                for base_name, abs_path in proofs.items():
                    if os.path.exists(abs_path):
                        final_zip.write(abs_path, arcname=base_name)
                        os.remove(abs_path)
                    else:
                        # delete corresponding record.
                        for report in reports:
                            if report.get("type") == "safe" and report.get("proof")[0] == base_name:
                                failed_reports.add(report)
                                break

                for report in reports:
                    if report.get("type") == "component" and report.get("name") == COMPONENT_MEA:
                        percent_of_unsafe_incomplete = 0
                        if mea_all_unsafes != 0:
                            percent_of_unsafe_incomplete = \
                                round(100 * mea_unsafe_incomplete / mea_all_unsafes, 2)

                        report["attrs"].append(self.__format_attr("Unsafes", str(mea_all_unsafes)))
                        report["attrs"].append(self.__format_attr("Unsafe-incomplete",
                                                                  f"{percent_of_unsafe_incomplete}"
                                                                  f"%"))
                        report["attrs"].append(self.__format_attr("Initial traces",
                                                                  str(mea_overall_initial_traces)))
                        report["attrs"].append(self.__format_attr("Filtered traces",
                                                                  str(mea_overall_filtered_traces)))
                        break

                if failed_reports:
                    self.logger.warning(f"Failed witnesses to process: {len(failed_reports)} "
                                        f"of {len(unsafes)}")
                    for report in failed_reports:
                        reports.remove(report)

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
                with zipfile.ZipFile(DEFAULT_SOURCES_ARCH, mode='w',
                                     compression=zipfile.ZIP_DEFLATED) as arch_obj:
                    for src_file, src_file_res in source_files.items():
                        arch_obj.write(src_file, arcname=src_file_res)
                final_zip.write(DEFAULT_SOURCES_ARCH)
                os.remove(DEFAULT_SOURCES_ARCH)

                # TODO: those sources may be duplicated.
                with zipfile.ZipFile(DEFAULT_COVERAGE_SOURCES_ARCH, mode='w',
                                     compression=zipfile.ZIP_DEFLATED) as arch_obj:
                    src_paths = set()
                    for src_file, arch_path in coverage_sources.items():
                        if arch_path not in src_paths:
                            arch_obj.write(src_file, arcname=arch_path)
                            src_paths.add(arch_path)
                final_zip.write(DEFAULT_COVERAGE_SOURCES_ARCH)
                os.remove(DEFAULT_COVERAGE_SOURCES_ARCH)

                self.__process_global_coverage(global_cov_files, final_zip)
                if self.global_coverage_element:
                    reports.append(self.global_coverage_element)

                with open(FINAL_REPORT, 'w', encoding='utf8') as f_results:
                    json.dump(reports, f_results, ensure_ascii=False, sort_keys=True, indent="\t")
                final_zip.write(FINAL_REPORT, arcname="reports.json")
                os.remove(FINAL_REPORT)

        os.chdir(cur_dir)
        if not self.debug:
            shutil.rmtree(export_dir, ignore_errors=True)
        self.logger.info("Exporting results has been completed")
