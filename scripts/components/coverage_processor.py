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
This component processes coverage for solved verification task.
"""

import json
import logging
import multiprocessing
import os
import re
import subprocess
import zipfile

from components import *
from components.component import Component
from coverage.lcov import LCOV

TAG_COVERAGE_MODE = "mode"
TAG_COVERAGE_PERCENT_MODE = "percent mode"
TAG_FULL_COVERAGE_MODE = "src cov mode"

COVERAGE_MODE_NONE = "none"  # Do not compute coverage.
COVERAGE_MODE_PERCENT = "percent"  # Present only percentage of coverage by lines/functions.
COVERAGE_MODE_FULL = "full"  # Present full coverage.
COVERAGE_MODES = [
    COVERAGE_MODE_NONE,
    COVERAGE_MODE_PERCENT,
    COVERAGE_MODE_FULL
]

COVERAGE_PERCENT_GENHTML = "genhtml"
COVERAGE_PERCENT_LOG = "log"

DEFAULT_COVERAGE_MODE = COVERAGE_MODE_FULL
DEFAULT_COVERAGE_FILES = ["coverage.info", "subcoverage.info"]
DEFAULT_WORK_DIRECTORY = "coverage"
DIRECTORY_WITH_GENERATED_FILES = "generated"

TAG_PERCENT = "percent"
TAG_COVERAGE = "coverage"
TAG_FUNCTIONS_STATISTICS = "functions statistics"
TAG_VALUES = "values"
INTERNAL_DIVIDER = "_&&&_"


def extract_internal_coverage(data: dict, function_coverage: dict, line_coverage: dict,
                              stats: dict):
    """
    Extract coverage for functions and lines.
    """
    __extract_internal_coverage(data.get(TAG_FUNCTION_COVERAGE, {}).get(TAG_COVERAGE, []),
                                function_coverage)
    __extract_internal_coverage(data.get(TAG_LINE_COVERAGE, []), line_coverage)
    for file, funcs in data.get(TAG_FUNCTIONS_STATISTICS, {}).get(TAG_STATISTICS, {}).items():
        if file not in stats:
            stats[file] = []
        if funcs:
            stats[file].extend(funcs)


def __extract_internal_coverage(input_data: list, output_data: dict):
    for elem_desc in input_data:
        covered_num = elem_desc[0]
        desc = elem_desc[1]
        for file_name, lines in desc.items():
            for line_number in lines:
                if isinstance(line_number, int):
                    __parse_coverage_lines(file_name, line_number, output_data, covered_num)
                elif isinstance(line_number, list):
                    min_number = line_number[0]
                    max_number = line_number[1]
                    for num in range(min_number, max_number + 1):
                        __parse_coverage_lines(file_name, num, output_data, covered_num)
                else:
                    logging.warning(
                        f"Unknown type for line number: {line_number} of {type(line_number)}")


def __parse_coverage_lines(file_name: str, line_number: int, output_data: dict, covered_num: int):
    encoded_elem = f"{file_name}{INTERNAL_DIVIDER}{line_number}"
    if encoded_elem not in output_data:
        output_data[encoded_elem] = 0
    output_data[encoded_elem] = max(output_data[encoded_elem], covered_num)


def merge_coverages(func_1: dict, func_2: dict, lines_1: dict, lines_2: dict, merge_type: str):
    """
    Merge coverage for several properties.
    """
    __merge_coverages(func_1, func_2, merge_type)
    __merge_coverages(lines_1, lines_2, merge_type)


def __merge_coverages(input_data: dict, output_data: dict, merge_type: str):
    for encoded_elem, covered_num in input_data.items():
        if merge_type == COVERAGE_MERGE_TYPE_UNION:
            output_data[encoded_elem] = max(output_data.get(encoded_elem, 0), covered_num)
        elif merge_type == COVERAGE_MERGE_TYPE_INTERSECTION:
            if encoded_elem not in output_data:
                output_data[encoded_elem] = covered_num
            else:
                output_data[encoded_elem] = min(output_data.get(encoded_elem, 0), covered_num)
        else:
            logging.warning(f"WARNING: unknown type of coverage merge: '{merge_type}'")


def write_coverage(counter: int, function_coverage: dict, line_coverage: dict, stats: dict) -> str:
    """
    Print coverage in archive.
    """
    generated_arch = f"gc_{counter}.zip"
    generated_cov = f"gc_{counter}.json"
    data = {
        TAG_FUNCTION_COVERAGE: {
            TAG_COVERAGE: [],
            TAG_STATISTICS: {}
        },
        TAG_LINE_COVERAGE: [],
        TAG_FUNCTIONS_STATISTICS: {
            TAG_STATISTICS: stats,
            TAG_VALUES: []
        },
        TAG_PERCENT: {}
    }
    __decode_coverage(function_coverage, data[TAG_FUNCTION_COVERAGE][TAG_COVERAGE])
    __decode_coverage(line_coverage, data[TAG_LINE_COVERAGE])
    functions_percent, lines_percent = _count_percent(function_coverage, line_coverage)
    data[TAG_PERCENT][TAG_FUNCTION_COVERAGE] = functions_percent
    data[TAG_PERCENT][TAG_LINE_COVERAGE] = lines_percent
    data[TAG_PERCENT][TAG_STATISTICS] = {}
    data[TAG_PERCENT][TAG_VALUES] = []
    with zipfile.ZipFile(generated_arch, mode='w', compression=zipfile.ZIP_DEFLATED) as arch_obj:
        with open(generated_cov, "w", encoding='utf8') as file_obj:
            json.dump(data, file_obj, ensure_ascii=False, sort_keys=True, indent="\t")
        arch_obj.write(generated_cov, arcname=DEFAULT_COVERAGE_FILE)
        os.remove(generated_cov)
    return generated_arch


def _count_percent(function_coverage: dict, line_coverage: dict) -> tuple:
    covered_functions, all_functions = __count_percent(function_coverage)
    covered_lines, all_lines = __count_percent(line_coverage)
    if not all_functions:
        all_functions = 1
    if not all_lines:
        all_lines = 1
    return round(covered_functions / all_functions * 100, 2), \
        round(covered_lines / all_lines * 100, 2)


def __count_percent(elements: dict) -> tuple:
    covered, counter = 0, 0
    for encoded_elem, covered_num in elements.items():
        if str(encoded_elem).startswith(TAG_SOURCES):
            counter += 1
            if covered_num > 0:
                covered += 1
    return covered, counter


def __decode_coverage(input_data: dict, output_data: list):
    tmp_result = {}
    for encoded_elem, covered_num in input_data.items():
        file_name, line_number = str(encoded_elem).split(INTERNAL_DIVIDER)
        line_number = json.loads(str(line_number))
        if covered_num not in tmp_result:
            tmp_result[covered_num] = {}
        if file_name not in tmp_result[covered_num]:
            tmp_result[covered_num][file_name] = []
        tmp_result[covered_num][file_name].append(line_number)
    for covered_num in sorted(tmp_result):
        output_data.append([covered_num, tmp_result[covered_num]])


class Coverage(Component):
    """
    Component for coverage processing.
    """
    def __init__(self, launcher_component: Component = None, basic_config=None, install_dir=None,
                 work_dir=None, default_source_file=None):
        if launcher_component:
            config = launcher_component.config
        else:
            config = basic_config
        super().__init__(COMPONENT_COVERAGE, config)
        if launcher_component:
            self.install_dir = launcher_component.install_dir
            self.launcher_dir = launcher_component.work_dir
        else:
            self.install_dir = install_dir
            self.launcher_dir = work_dir
        self.mode = self.component_config.get(TAG_COVERAGE_MODE, DEFAULT_COVERAGE_MODE)
        self.percent_mode = self.component_config.get(TAG_COVERAGE_PERCENT_MODE,
                                                      COVERAGE_PERCENT_LOG)
        self.src_cov_mode = self.component_config.get(TAG_FULL_COVERAGE_MODE, "full")
        self.internal_logger = logging.getLogger(name=COMPONENT_COVERAGE)
        self.internal_logger.setLevel(self.logger.level)
        self.default_source_file = default_source_file

    def compute_coverage(self, source_dirs: set, launch_directory: str,
                         queue: multiprocessing.Queue = None, work_dir=None):
        """
        Main method for coverage processing.
        """
        cov_lines, cov_funcs = 0.0, 0.0
        if self.mode == COVERAGE_MODE_NONE:
            return
        for file in DEFAULT_COVERAGE_FILES:
            if os.path.exists(os.path.join(launch_directory, file)):
                os.chdir(launch_directory)
                if self.percent_mode == COVERAGE_PERCENT_GENHTML:
                    try:
                        process_out = subprocess.check_output(
                            "genhtml {file} --ignore-errors source",
                            shell=True, stderr=subprocess.STDOUT)
                        for line in process_out.splitlines():
                            line = line.decode("utf-8", errors="ignore")
                            res = re.search(r'lines......: (.+)% ', line)
                            if res:
                                cov_lines = float(res.group(1))
                            res = re.search(r'functions..: (.+)% ', line)
                            if res:
                                cov_funcs = float(res.group(1))
                    except Exception as exception:
                        self.logger.warning(f"Exception during coverage processing: {exception}",
                                            exc_info=True)
                elif self.percent_mode == COVERAGE_PERCENT_LOG:
                    with open(LOG_FILE, encoding='utf8') as f_log:
                        for line in f_log.readlines():
                            res = re.search(r'Function coverage:(\s+)(\S+)$', line)
                            if res:
                                cov_funcs = round(100 * float(res.group(2)), 2)
                            res = re.search(r'Line coverage:(\s+)(\S+)$', line)
                            if res:
                                cov_lines = round(100 * float(res.group(2)), 2)
                else:
                    self.logger.warning(f"Unknown coverage mode: {self.percent_mode}")
                if self.mode == COVERAGE_MODE_FULL:
                    self.__full_coverage(source_dirs, os.path.abspath(file), work_dir)
                break
        os.chdir(self.launcher_dir)

        if queue:
            data = self.get_component_full_stats()
            data[TAG_COVERAGE_LINES] = cov_lines
            data[TAG_COVERAGE_FUNCS] = cov_funcs
            queue.put(data)

    def __full_coverage(self, source_dirs: set, coverage_file: str, work_dir: str):
        dummy_dir = ""
        for src_dir in source_dirs:
            if os.path.exists(os.path.join(src_dir, CLADE_WORK_DIR)):
                dummy_dir = os.path.join(src_dir, CLADE_WORK_DIR)
                break

        if not work_dir:
            work_dir = self.launcher_dir
        lcov = LCOV(self.internal_logger, coverage_file, dummy_dir, source_dirs, [],
                    work_dir, self.src_cov_mode,
                    ignore_files={os.path.join(DIRECTORY_WITH_GENERATED_FILES,
                                               COMMON_HEADER_FOR_RULES)},
                    default_file=self.default_source_file)

        archive = os.path.join(DEFAULT_COVERAGE_ARCH)
        files = [DEFAULT_COVERAGE_FILE] + list(lcov.arcnames.keys())
        with open(archive, mode='w+b', buffering=0) as arch_obj:
            with zipfile.ZipFile(arch_obj, mode='w', compression=zipfile.ZIP_DEFLATED) as extr_obj:
                with open(DEFAULT_COVERAGE_SOURCE_FILES, mode="w", encoding='utf8') as file_obj:
                    for file in files:
                        arch_name = lcov.arcnames.get(file, os.path.basename(file))
                        if file == DEFAULT_COVERAGE_FILE:
                            extr_obj.write(file, arcname=arch_name)
                        else:
                            file_obj.write(f"{file};{arch_name}\n")
                os.fsync(extr_obj.fp)
