# Continuous Verification Framework - processing and managing verification results.
# Repository: https://github.com/ispras/cv
#
# Copyright © 2025 Vitalii Mordan, ISP RAS
#
# SPDX-License-Identifier: Apache-2.0

# pylint: disable=too-few-public-methods, invalid-name
"""
This module describes internal data structures.
"""

import glob
import json
import os
import re
import shutil
import sys
import time
from enum import Enum
from xml.etree import ElementTree

from components import LOG_FILE
from components.mea import MEA
from models.tags import Tag, ComponentName, Extension, Resource, WitnessType


class Verdict(str, Enum):
    """
    Basic verdict of a verification task.
    """
    SAFE = "TRUE"
    UNSAFE = "FALSE"
    UNKNOWN = "UNKNOWN"


DEFAULT_SUBSYSTEM = "."

TERMINATION_SUCCESS = "SUCCESS"

ADDITIONAL_RESOURCES = [
    'blkio-read', 'blkio-write', 'error traces', 'cpuenergy'
]


class Property(str, Enum):
    """
    Constants related to the property.
    """
    COVERAGE = "coverage"
    COMMON = "common"


def _to_str(val) -> str:
    if isinstance(val, Enum):
        val = val.value
    return str(val)


DEFAULT_PROPERTIES_DIR = "properties"
DEFAULT_PROPERTIES_DESC_FILE = "properties.json"
PROPERTY_IS_MOVE_OUTPUT = "is move output"
PROPERTY_SPECIFICATION_AUTOMATON = "specification automaton"
PROPERTY_MODE = "mode"
PROPERTY_OPTIONS = "options"
PROPERTY_MAIN_GENERATION_STRATEGY = "main generation strategy"
PROPERTY_IS_RELEVANCE = "is relevance"
PROPERTY_IS_ALL_TRACES_FOUND = "is all traces found"


class EntryPointDesc:
    """
    Representation of entry points description.
    """

    def __init__(self, files: list, identifier: str):
        self.id = identifier
        self.short_name = re.sub(r"\W", "_", identifier)  # Should be used in path concatenations.
        self.optimize = False
        self.subsystems = []
        self.data = {}
        for file in files:
            with open(file, errors='ignore', encoding="utf8") as file_obj:
                data = json.load(file_obj)
            metadata = data.get(Tag.METADATA, {})
            entrypoints = data[Tag.ENTRYPOINTS]
            self.optimize = self.optimize or metadata.get(Tag.OPTIMIZE, False)
            self.subsystems.append(metadata.get(Tag.SUBSYSTEM, DEFAULT_SUBSYSTEM))
            for caller, params in entrypoints.items():
                self.data[caller] = params
                self.data[caller][Tag.METADATA] = metadata

    def __str__(self):
        return self.id


class VerificationTask:
    """
    Representation of a verification task.
    """

    def __init__(self, entry_desc: EntryPointDesc, rule: str, mode: str, entrypoint,
                 path_to_verifier, cil_file):
        self.entry_desc = entry_desc
        self.rule = rule
        self.entrypoint = entrypoint
        self.mode = mode
        self.path_to_verifier = path_to_verifier
        self.cil_file = cil_file
        self.name = "_".join([self.entry_desc.id, self.rule, self.entrypoint])

    def copy(self):
        """
        Make a copy of verification task.
        """
        return type(self)(self.entry_desc, self.rule, self.mode, self.entrypoint,
                          self.path_to_verifier, self.cil_file)


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
        self.et_num = 0
        self.filtered = 0
        self.relevant = 0

    def add_result(self, verification_result):
        """
        Add intermediate resources usages to global statistics.
        """
        self.cpu += verification_result.cpu
        self.wall += verification_result.wall
        self.et_num += verification_result.initial_traces
        self.filtered += verification_result.filtered_traces
        if verification_result.relevant:
            self.relevant += 1
        if verification_result.verdict == Verdict.SAFE:
            self.safes += 1
        elif verification_result.verdict == Verdict.UNSAFE:
            self.unsafes += 1
        else:
            self.unknowns += 1
        self.mem_average += verification_result.mem

    def __add_overall(self, cpu, wall, et_num, filtered, relevant):
        self.cpu += cpu
        self.wall += wall
        self.et_num += et_num
        self.filtered += filtered
        self.relevant += relevant

    def sum(self, info):
        """
        Complete resource measurements.
        """
        self.relevant = max(self.relevant, info.relevant)
        info.relevant = 0
        self.__add_overall(info.cpu, info.wall, info.et_num, info.filtered, info.relevant)
        self.mem_average = max(self.mem_average, info.mem_average)
        self.safes += info.safes
        self.unsafes += info.unsafes
        self.unknowns += info.unknowns

    def sum_memory(self):
        """
        Summary of memory usage.
        """
        overall = self.safes + self.unknowns + self.unsafes
        if overall:
            self.mem_average = int(self.mem_average / overall)
        else:
            self.mem_average = 0

    def __str__(self):
        return ";".join([str(self.safes), str(self.unsafes), str(self.unknowns), str(self.relevant),
                         str(self.et_num), str(self.filtered), str(round(self.cpu, -3)),
                         str(round(self.wall, -3)), str(round(self.mem_average / 1000))])


class VerificationResults:
    """
    Representation of a result for a given verification task.
    """

    def __init__(self, verification_task, config: dict):
        if verification_task:
            self.id = verification_task.entry_desc.id
            self.rule = verification_task.rule
            self.entrypoint = verification_task.entrypoint
        else:
            self.id = None
            self.rule = None
            self.entrypoint = None
        self.cpu = 0
        self.mem = 0
        self.wall = 0
        self.verdict = Verdict.UNKNOWN
        self.termination_reason = ""
        self.relevant = False
        self.initial_traces = 0
        self.work_dir = None
        self.cov_lines = 0.0
        self.cov_funcs = 0.0
        self.filtered_traces = 0
        self.debug = config.get(Tag.DEBUG, False)
        self.config = config
        self.coverage_resources = {}
        self.mea_resources = {}
        self.resources = {}

    def is_equal(self, verification_task: VerificationTask):
        """
        Compare two verification results.
        """
        return self.id == verification_task.entry_desc.id and \
            self.rule == verification_task.rule and \
            self.entrypoint == verification_task.entrypoint

    def get_name(self) -> str:
        """
        Returns unique name of a verification result.
        """
        return "_".join([str(self.entrypoint), str(self.rule), str(self.entrypoint)])

    def __parse_xml_node(self, columns):
        for column in columns:
            title = column.attrib['title']
            if title == 'status':
                self.verdict = column.attrib['value']
                if 'true' in self.verdict:
                    self.verdict = Verdict.SAFE
                    self.termination_reason = TERMINATION_SUCCESS
                elif 'false' in self.verdict:
                    self.verdict = Verdict.UNSAFE
                    self.termination_reason = TERMINATION_SUCCESS
                else:
                    self.termination_reason = self.verdict
                    self.verdict = Verdict.UNKNOWN
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
            elif title in ['memUsage', 'memory']:
                value = column.attrib['value']
                if str(value).endswith("B"):
                    value = value[:-1]
                self.mem = int(int(value) / 1000000)
            elif title in ADDITIONAL_RESOURCES:
                value = column.attrib['value']
                if str(value).endswith("B") or str(value).endswith("J"):
                    value = value[:-1]
                self.resources[title] = int(float(value))

    def parse_output_dir(self, launch_dir: str, install_dir: str, result_dir: str,
                         parsed_columns=None, ignore_src_prefixes=None):
        """
        Get verification results from launch directory.
        """
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

            with open(log_file, errors='ignore', encoding="utf8") as f_res:
                for line in f_res.readlines():
                    res = re.search(r'Number of refinements:(\s+)(\d+)', line)
                    if res:
                        if int(res.group(2)) > 1:
                            self.relevant = True
            if not parsed_columns:
                shutil.move(log_file, f"{launch_dir}/{LOG_FILE}")
        except IndexError:
            print(f"WARNING: log file was not found for entry point '{self.entrypoint}'")

        error_traces = glob.glob(f"{launch_dir}/*{Extension.GRAPHML}")
        self.initial_traces = len(error_traces)
        if self.verdict == Verdict.SAFE and not \
                self.config.get(ComponentName.EXPORTER, {}).get(Tag.ADD_VERIFIER_PROOFS, True):
            self.initial_traces = 0
        self.filtered_traces = self.initial_traces

        if not self.verdict == Verdict.SAFE:
            self.relevant = True

        # If there is only one trace, filtering will not be performed, and it will not be examined.
        if self.initial_traces == 1:
            # Trace should be checked if it is correct or not.
            start_time_cpu = time.process_time()
            start_wall_time = time.time()
            mea = MEA(self.config, error_traces, install_dir, self.rule, result_dir,
                      remove_prefixes=ignore_src_prefixes)
            is_exported, witness_type = mea.process_traces_without_filtering()
            if is_exported:
                # Trace is fine, just recheck final verdict.
                if witness_type == WitnessType.VIOLATION:
                    # Change global verdict to Unsafe,
                    # if there is at least one correct violation witness.
                    self.verdict = Verdict.UNSAFE
                if witness_type == WitnessType.CORRECTNESS:
                    self.verdict = Verdict.SAFE
            else:
                # Trace is bad, most likely verifier was killed during its printing,
                # so just delete it.
                if self.verdict == Verdict.UNSAFE and witness_type == WitnessType.VIOLATION:
                    # TODO: Add exception text to log.
                    self.verdict = Verdict.UNKNOWN
                self.initial_traces = 0
                self.filtered_traces = 0
            self.mea_resources[Resource.CPU_TIME] = time.process_time() - start_time_cpu
            self.mea_resources[Resource.WALL_TIME] = time.time() - start_wall_time
            self.mea_resources[Resource.MEMORY_USAGE] = mea.memory

        # Remove auxiliary files.
        if not self.debug:
            for file in glob.glob(os.path.join(launch_dir, "benchmark*")):
                if os.path.isdir(file):
                    shutil.rmtree(file, ignore_errors=True)
                else:
                    os.remove(file)

    def filter_traces(self, launch_dir: str, install_dir: str, result_dir: str, remove_src_prefixes=None):
        """
        Perform Multiple Error Analysis to filter found error traces (only for several traces).
        """
        start_time_cpu = time.process_time()
        start_wall_time = time.time()
        traces = glob.glob(f"{launch_dir}/witness*")
        mea = MEA(self.config, traces, install_dir, self.rule, result_dir, remove_prefixes=remove_src_prefixes)
        self.filtered_traces = len(mea.filter())
        if self.filtered_traces:
            self.verdict = Verdict.UNSAFE
        self.mea_resources[Resource.CPU_TIME] = time.process_time() - start_time_cpu + mea.cpu_time
        self.mea_resources[Resource.WALL_TIME] = time.time() - start_wall_time
        self.mea_resources[Resource.MEMORY_USAGE] = mea.memory

    def parse_line(self, line: str):
        """
        Parse a given line with verification results.
        """
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
        self.mea_resources[Resource.CPU_TIME] = float(values[14])

    def __str__(self):
        return ";".join([_to_str(self.id), _to_str(self.rule), _to_str(self.entrypoint),
                         _to_str(self.verdict), _to_str(self.termination_reason), _to_str(self.cpu),
                         _to_str(self.wall), _to_str(self.mem), _to_str(self.relevant),
                         _to_str(self.initial_traces), _to_str(self.filtered_traces),
                         _to_str(self.work_dir), _to_str(self.cov_lines), _to_str(self.cov_funcs),
                         _to_str(self.mea_resources.get(Resource.CPU_TIME, 0.0))])

    def print_resources(self):
        """
        Encode verification results into line.
        """
        res = []
        for resource in ADDITIONAL_RESOURCES:
            if resource == "error traces":
                value = self.filtered_traces
            else:
                value = self.resources.get(resource, 0)
            res.append(str(value))
        return ";".join(res)


class PropertiesDescription:
    """
    Representation of a property description.
    """

    def __init__(self, plugin_path=""):
        self.property_desc = {}
        # Here we take basic properties description file and the one for plugin.
        basic_properties_desc_file = os.path.join(DEFAULT_PROPERTIES_DIR,
                                                  DEFAULT_PROPERTIES_DESC_FILE)
        if not os.path.exists(basic_properties_desc_file):
            # Basic file is not required for benchmarks processing.
            return

        for file in [basic_properties_desc_file, plugin_path]:
            if not file or not os.path.exists(file):
                # File may not be specified for plugin
                continue
            with open(file, "r", errors='ignore', encoding="utf8") as file_obj:
                content = json.load(file_obj)
                for prop, desc in content.items():
                    self.property_desc[prop] = desc
                    if PROPERTY_MODE not in desc:
                        sys.exit(f"Property file is incorrect: property {prop} is missing "
                                 f"{PROPERTY_MODE} attribute")

    def get_property_arg(self, prop: str, arg: str, ignore_missing=False):
        """
        Get a value of an argument for the property.
        """
        property_desc = self.property_desc.get(prop, {})
        if not property_desc and not ignore_missing:
            sys.exit(f"Property {prop} was not in a description")
        default_arg = ""
        if arg == PROPERTY_IS_MOVE_OUTPUT:
            default_arg = False
        elif arg == PROPERTY_OPTIONS:
            default_arg = {}
        elif arg == PROPERTY_SPECIFICATION_AUTOMATON:
            default_arg = ""
        elif arg == PROPERTY_MAIN_GENERATION_STRATEGY:
            default_arg = ""
        elif arg == PROPERTY_IS_RELEVANCE:
            default_arg = True
        elif arg == PROPERTY_IS_ALL_TRACES_FOUND:
            default_arg = False
        if arg == PROPERTY_MODE and arg not in property_desc:
            sys.exit(f"Mode was not specified for property {prop}")
        return property_desc.get(arg, default_arg)

    def get_properties(self):
        """
        Get names of all properties.
        """
        return self.property_desc.keys()

    def get_property_arg_for_all(self, arg: str) -> dict:
        """
        Get values of a given argument for all properties.
        """
        result = {}
        for prop in self.get_properties():
            result[prop] = self.get_property_arg(prop, arg)
        return result
