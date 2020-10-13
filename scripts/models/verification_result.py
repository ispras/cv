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

import glob
import json
import os
import re
import shutil
import time
from xml.etree import ElementTree

from components import *
from components.mea import MEA

TAG_OPTIMIZE = "optimize"


def to_str(val) -> str:
    return "{}".format(val)


class EntryPointDesc:
    def __init__(self, file: str, identifier: str):
        self.file = file
        with open(file, errors='ignore') as fd:
            data = json.load(fd)
            metadata = data.get(TAG_METADATA, {})
            self.optimize = metadata.get(TAG_OPTIMIZE, False)
            self.subsystem = metadata.get(TAG_SUBSYSTEM, ".")
        self.id = identifier  # Path in the entrypoints directory (may contain subdirectories).
        self.short_name = re.sub(r"\W", "_", identifier)  # Should be used in path concatenations.

    def __str__(self):
        return self.id


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

    def add_result(self, verification_result):
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
        self.mea_resources = dict()
        self.resources = dict()

    def is_equal(self, verification_task: VerificationTask):
        return self.id == verification_task.entry_desc.subsystem and \
               self.rule == verification_task.rule and \
               self.entrypoint == verification_task.entrypoint

    def get_name(self) -> str:
        return "_".join([str(self.entrypoint), str(self.rule), str(self.entrypoint)])

    def __parse_xml_node(self, columns):
        for column in columns:
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
                if str(value).endswith("s"):
                    value = value[:-1]
                self.cpu = float(value)
            elif title == 'walltime':
                value = column.attrib['value']
                if str(value).endswith("s"):
                    value = value[:-1]
                self.wall = float(value)
            elif title == 'memUsage' or title == 'memory':
                value = column.attrib['value']
                if str(value).endswith("B"):
                    value = value[:-1]
                self.mem = int(int(value) / 1000000)
            elif title in ADDITIONAL_RESOURCES:
                value = column.attrib['value']
                if str(value).endswith("B"):
                    value = value[:-1]
                self.resources[title] = int(value)

    def parse_output_dir(self, launch_dir: str, install_dir: str, result_dir: str, parsed_columns=None):
        # Process BenchExec xml output file.
        if parsed_columns:
            self.__parse_xml_node(parsed_columns)
        else:
            for file in glob.glob(os.path.join(launch_dir, 'benchmark*.xml')):
                tree = ElementTree.ElementTree()
                tree.parse(file)
                root = tree.getroot()
                # for column in root.findall('./run/column'):
                self.__parse_xml_node(root.findall('./run/column'))

        # Process verifier log file.
        try:
            cur_dir_logs = glob.glob(os.path.join(launch_dir, LOG_FILE))
            if cur_dir_logs:
                log_file = cur_dir_logs[0]
            else:
                log_file = glob.glob(os.path.join(launch_dir, 'benchmark*logfiles/*.log'))[0]

            with open(log_file, errors='ignore') as f_res:
                for line in f_res.readlines():
                    res = re.search(r'Number of refinements:(\s+)(\d+)', line)
                    if res:
                        if int(res.group(2)) > 1:
                            self.relevant = True
            if not parsed_columns:
                shutil.move(log_file, "{}/{}".format(launch_dir, LOG_FILE))
        except IndexError:
            print("WARNING: log file was not found for entry point '{}'".format(self.entrypoint))
            pass

        error_traces = glob.glob("{}/*{}".format(launch_dir, GRAPHML_EXTENSION))
        self.initial_traces = len(error_traces)
        if self.verdict == VERDICT_SAFE and not \
                self.config.get(COMPONENT_EXPORTER, {}).get(TAG_ADD_VERIFIER_PROOFS, True):
            self.initial_traces = 0
        self.filtered_traces = self.initial_traces

        if not self.verdict == VERDICT_SAFE:
            self.relevant = True

        # If there is only one trace, filtering will not be performed and it will not be examined.
        if self.initial_traces == 1:
            # Trace should be checked if it is correct or not.
            start_time_cpu = time.process_time()
            start_wall_time = time.time()
            mea = MEA(self.config, error_traces, install_dir, self.rule, result_dir)
            is_exported, witness_type = mea.process_traces_without_filtering()
            if is_exported:
                # Trace is fine, just recheck final verdict.
                if witness_type == WITNESS_VIOLATION:
                    # Change global verdict to Unsafe, if there is at least one correct violation witness.
                    self.verdict = VERDICT_UNSAFE
                if witness_type == WITNESS_CORRECTNESS:
                    self.verdict = VERDICT_SAFE
            else:
                # Trace is bad, most likely verifier was killed during its printing, so just delete it.
                if self.verdict == VERDICT_UNSAFE and witness_type == WITNESS_VIOLATION:
                    # TODO: Add exception text to log.
                    self.verdict = VERDICT_UNKNOWN
                self.initial_traces = 0
                self.filtered_traces = 0
            self.mea_resources[TAG_CPU_TIME] = time.process_time() - start_time_cpu
            self.mea_resources[TAG_WALL_TIME] = time.time() - start_wall_time
            self.mea_resources[TAG_MEMORY_USAGE] = mea.memory

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
        start_wall_time = time.time()
        traces = glob.glob("{}/witness*".format(launch_dir))
        mea = MEA(self.config, traces, install_dir, self.rule, result_dir)
        self.filtered_traces = len(mea.filter())
        if self.filtered_traces:
            self.verdict = VERDICT_UNSAFE
        self.mea_resources[TAG_CPU_TIME] = time.process_time() - start_time_cpu + mea.cpu_time
        self.mea_resources[TAG_WALL_TIME] = time.time() - start_wall_time
        self.mea_resources[TAG_MEMORY_USAGE] = mea.memory

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
        self.mea_resources[TAG_CPU_TIME] = float(values[14])

    def __str__(self):
        return ";".join([to_str(self.id), to_str(self.rule), to_str(self.entrypoint), to_str(self.verdict),
                         to_str(self.termination_reason), to_str(self.cpu), to_str(self.wall), to_str(self.mem),
                         to_str(self.relevant), to_str(self.initial_traces), to_str(self.filtered_traces),
                         to_str(self.work_dir), to_str(self.cov_lines), to_str(self.cov_funcs),
                         to_str(self.mea_resources.get(TAG_CPU_TIME, 0.0))])

    def print_resources(self):
        res = list()
        for resource in ADDITIONAL_RESOURCES:
            if resource == "error traces":
                value = self.filtered_traces
            else:
                value = self.resources.get(resource, 0)
            res.append(str(value))
        return ";".join(res)
