#
# CV is a framework for continuous verification.
# This module was based on Klever-CV repository (https://github.com/mutilin/klever/tree/cv-v2.0).
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
Module for lcov coverage processing.
"""

import json
import os
import re


def _add_to_coverage(merged_coverage_info, coverage_info):
    for file_name in coverage_info:
        merged_coverage_info.setdefault(file_name, {
            'total functions': coverage_info[file_name][0]['total functions'],
            'covered lines': {},
            'covered functions': {},
            'covered function names': []
        })

        for coverage in coverage_info[file_name]:
            for path in ('covered lines', 'covered functions'):
                for line, value in coverage[path].items():
                    merged_coverage_info[file_name][path].setdefault(line, 0)
                    merged_coverage_info[file_name][path][line] += value
            if coverage.get('covered function names'):
                for name in coverage['covered function names']:
                    if name not in merged_coverage_info[file_name]['covered function names']:
                        merged_coverage_info[file_name]['covered function names'].append(name)


def _get_coverage(merged_coverage_info):
    # Map combined coverage to the required format
    line_coverage = {}
    function_coverage = {}
    function_statistics = {}
    function_name_staticitcs = {}

    for file_name in list(merged_coverage_info.keys()):
        for line, value in merged_coverage_info[file_name]['covered lines'].items():
            line_coverage.setdefault(value, {})
            line_coverage[value].setdefault(file_name, [])
            line_coverage[value][file_name].append(int(line))

        for line, value in merged_coverage_info[file_name]['covered functions'].items():
            function_coverage.setdefault(value, {})
            function_coverage[value].setdefault(file_name, [])
            function_coverage[value][file_name].append(int(line))

        function_statistics[file_name] = [len(merged_coverage_info[file_name]['covered functions']),
                                          merged_coverage_info[file_name]['total functions']]

        if merged_coverage_info[file_name].get('covered function names'):
            function_name_staticitcs[file_name] = \
                list(merged_coverage_info[file_name]['covered function names'])
    function_name_staticitcs['overall'] = None

    # Merge covered lines into the range
    for key, value in line_coverage.items():
        for file_name, lines in value.items():
            value[file_name] = __build_ranges(lines)

    return {
        'line coverage': [[key, value] for key, value in line_coverage.items()],
        'function coverage': {
            'statistics': function_statistics,
            'coverage': [[key, value] for key, value in function_coverage.items()]
        },
        'functions statistics': {'statistics': function_name_staticitcs, 'values': []}
    }


def __build_ranges(lines):
    if not lines:
        return []
    res = []
    prev = 0
    lines = sorted(lines)
    for i in range(1, len(lines)):
        if lines[i] != lines[i - 1] + 1:
            # The sequence is broken.
            if i - 1 != prev:
                # There is more than one line in the sequence. .
                if i - 2 == prev:
                    # There is more than two lines in the sequence. Add the range.
                    res.append(lines[prev])
                    res.append(lines[i - 1])
                else:
                    # Otherwise, add these lines separately.
                    res.append([lines[prev], lines[i - 1]])
            else:
                # Just add a single non-sequence line.
                res.append(lines[prev])
            prev = i

    # This step is the same as in the loop body.
    if prev != len(lines) - 1:
        if prev == len(lines) - 2:
            res.append(lines[prev])
            res.append(lines[-1])
        else:
            res.append([lines[prev], lines[-1]])
    else:
        res.append(lines[prev])

    return res


def _make_relative_path(dirs, file_or_dir, absolutize=False):
    # Normalize paths first of all.
    dirs = [os.path.normpath(directory) for directory in dirs]
    file_or_dir = os.path.normpath(file_or_dir)

    # Check all dirs are absolute or relative.
    is_dirs_abs = False
    if all(os.path.isabs(directory) for directory in dirs):
        is_dirs_abs = True
    elif all(not os.path.isabs(directory) for directory in dirs):
        pass
    else:
        raise ValueError('Can not mix absolute and relative dirs')

    if os.path.isabs(file_or_dir):
        # Making absolute file_or_dir relative to relative dirs has no sense.
        if not is_dirs_abs:
            return file_or_dir
    else:
        # One needs to absolutize file_or_dir since it can be relative to Clade storage.
        if absolutize:
            if not is_dirs_abs:
                raise ValueError('Do not absolutize file_or_dir for relative dirs')

            file_or_dir = os.path.join(os.path.sep, file_or_dir)
        # file_or_dir is already relative.
        elif is_dirs_abs:
            return file_or_dir

    # Find and return if so path relative to the longest directory.
    for directory in sorted(dirs, key=lambda t: len(t), reverse=True):
        if os.path.commonpath([file_or_dir, directory]) == directory:
            return os.path.relpath(file_or_dir, directory)

    return file_or_dir


class LCOV:
    """
    Coverage processor for lcov results
    """
    NEW_FILE_PREFIX = "TN:"
    EOR_PREFIX = "end_of_record"
    FILENAME_PREFIX = "SF:"
    LINE_PREFIX = "DA:"
    FUNCTION_PREFIX = "FNDA:"
    FUNCTION_NAME_PREFIX = "FN:"
    PARIALLY_ALLOWED_EXT = ('.c', '.i', '.c.aux')

    def __init__(self, logger, coverage_file, clade_dir, source_dirs, search_dirs, main_work_dir,
                 completeness, coverage_id=None, coverage_info_dir=None, collect_functions=True,
                 ignore_files=None, default_file=None):
        # Public
        self.logger = logger
        self.coverage_file = coverage_file
        self.clade_dir = os.path.normpath(clade_dir)
        self.source_dirs = [os.path.realpath(p) for p in source_dirs]
        self.search_dirs = [os.path.realpath(p) for p in search_dirs]
        self.main_work_dir = main_work_dir
        self.completeness = completeness
        self.coverage_info_dir = coverage_info_dir
        self.arcnames = {}
        self.collect_functions = collect_functions
        if ignore_files is None:
            ignore_files = set()
        self.ignore_files = ignore_files
        self.default_file = default_file
        # TODO: specify this option
        self._is_read_line_directives = False

        # Sanity checks
        if self.completeness not in ('full', 'src_only', 'none', None):
            raise NotImplementedError(f"Coverage type {self.completeness} is not supported")

        # Import coverage
        try:
            if self.completeness in ('full', 'src_only'):
                self.coverage_info = self.parse()

                if coverage_id:
                    with open(coverage_id, 'w', encoding='utf-8') as file_obj:
                        json.dump(self.coverage_info, file_obj, ensure_ascii=True, sort_keys=True,
                                  indent="\t")

                coverage = {}
                _add_to_coverage(coverage, self.coverage_info)
                with open('coverage.json', 'w', encoding='utf-8') as file_obj:
                    json.dump(_get_coverage(coverage), file_obj, ensure_ascii=True, sort_keys=True,
                              indent=None)
        except Exception:
            if os.path.isfile('coverage.json'):
                os.remove('coverage.json')
            raise

    def get_src_files_map(self, new_name: str, results: dict):
        if not results:
            with open(new_name, encoding='utf8') as fd_cil:
                line_num = 1
                orig_file_id = None
                orig_file_line_num = 0
                line_preprocessor_directive = re.compile(r'\s*#line\s+(\d+)\s*(.*)')
                for line in fd_cil:
                    m = line_preprocessor_directive.match(line)
                    if m:
                        orig_file_line_num = int(m.group(1))
                        if m.group(2):
                            tmp_file = m.group(2)[1:-1]
                            # Do not treat artificial file references
                            if not os.path.basename(tmp_file) == '<built-in>':
                                orig_file_id = tmp_file
                    else:
                        if orig_file_id and orig_file_line_num:
                            results[line_num] = (orig_file_id, orig_file_line_num)
                        orig_file_line_num += 1
                    line_num += 1

    def parse(self) -> dict:
        """
        Parses lcov results
        """
        dir_map = (
            ('sources', self.source_dirs),
            ('specifications', (
                os.path.realpath(os.path.join(self.main_work_dir, 'job', 'root', 'specifications')),
            )),
            ('generated', (
                os.path.realpath(self.main_work_dir),
            ))
        )

        ignore_file = False

        if not os.path.isfile(self.coverage_file):
            raise FileNotFoundError(f'There is no coverage file {self.coverage_file}')

        def __normalize_path(real_file_name: str) -> (bool, str):
            res_file_name = None
            real_file_name = os.path.normpath(real_file_name)
            if self.default_file:
                # TODO: dirty workaround (required for specific cases).
                dw_name = re.sub(r'.+/vcloud-\S+/worker/working_dir_[^/]+/', '',
                                 real_file_name)
                real_file_name = self.default_file
                for source_dir in self.source_dirs:
                    for tmp_file_name in [self.default_file, dw_name]:
                        tmp_file_name = os.path.join(source_dir, tmp_file_name)
                        if os.path.exists(tmp_file_name):
                            real_file_name = tmp_file_name
                            break
            tmp_file = os.path.join(os.path.sep, _make_relative_path([self.clade_dir], real_file_name))
            if os.path.isfile(real_file_name):
                for dest, srcs in dir_map:
                    for src in srcs:
                        if os.path.commonpath([real_file_name, src]) != src:
                            continue
                        if dest in ('generated', 'specifications'):
                            if self.completeness == "src_only":
                                is_ignore_file = True
                                break
                            res_file_name = os.path.join(dest, os.path.basename(tmp_file))
                        else:
                            res_file_name = os.path.join(dest, os.path.relpath(tmp_file, src))

                        if res_file_name in self.ignore_files:
                            continue
                        is_ignore_file = False
                        break
                    else:
                        continue
                    break
                # This "else" corresponds "for"
                else:
                    # Check other prefixes
                    res_file_name = _make_relative_path(self.search_dirs, tmp_file)
                    if res_file_name == tmp_file:
                        is_ignore_file = True
                    else:
                        is_ignore_file = False
                        res_file_name = os.path.join('specifications', res_file_name)
            else:
                is_ignore_file = True
            return is_ignore_file, res_file_name

        # Parsing coverage file
        coverage_info = {}
        src_files_map = {}

        with open(self.coverage_file, encoding='utf-8') as file_obj:
            for line in file_obj:
                line = line.rstrip('\n')

                if ignore_file and not line.startswith(self.FILENAME_PREFIX):
                    continue

                if line.startswith(self.NEW_FILE_PREFIX):
                    # Clean
                    covered_lines = {}
                    function_to_line = {}
                    function_by_file = {}
                    covered_functions = {}
                    count_covered_functions = {}
                elif line.startswith(self.FILENAME_PREFIX):
                    # Get file name, determine his directory and determine, should we ignore this
                    extracted_file_name = line[len(self.FILENAME_PREFIX):]
                    ignore_file, normalized_file_name = __normalize_path(extracted_file_name)
                    if normalized_file_name:  # ~ CIL file
                        if not self._is_read_line_directives:
                            self.get_src_files_map(extracted_file_name, src_files_map)
                            for _, info in src_files_map.items():
                                new_file_name_id, _ = info
                                _, new_file_name_id_norm = __normalize_path(new_file_name_id)
                                if new_file_name_id_norm:
                                    self.arcnames[new_file_name_id] = new_file_name_id_norm

                elif line.startswith(self.LINE_PREFIX):
                    # Coverage of the specified line
                    splts = line[len(self.LINE_PREFIX):].split(',')
                    cil_line = int(splts[0])
                    if cil_line in src_files_map:
                        target_file, target_line = src_files_map[cil_line]
                        if target_file not in covered_lines:
                            covered_lines[target_file] = {}
                        covered_lines[target_file][target_line] = int(splts[1])
                elif line.startswith(self.FUNCTION_NAME_PREFIX):
                    # Mapping of the function name to the line number
                    splts = line[len(self.FUNCTION_NAME_PREFIX):].split(',')
                    cil_line = int(splts[0])
                    function_to_line.setdefault(splts[1], 0)
                    function_to_line[splts[1]] = cil_line
                    if cil_line in src_files_map:
                        target_file, target_line = src_files_map[cil_line]
                        if target_file not in function_by_file:
                            function_by_file[target_file] = {}
                        function_by_file[target_file][splts[1]] = target_line
                elif line.startswith(self.FUNCTION_PREFIX):
                    # Coverage of the specified function
                    splts = line[len(self.FUNCTION_PREFIX):].split(',')
                    if splts[0] == "0":
                        continue
                    func_name = splts[1]
                    cil_line = function_to_line.get(func_name, None)

                    if cil_line and cil_line in src_files_map:
                        target_file, target_line = src_files_map[cil_line]
                        if target_file not in covered_functions:
                            covered_functions[target_file] = {}
                            count_covered_functions[target_file] = 0
                        covered_functions[target_file][target_line] = int(splts[0])
                        count_covered_functions[target_file] += 1
                elif line.startswith(self.EOR_PREFIX):
                    # End coverage for the specific file`

                    # Add functions, which were not covered

                    for orig_file, arc_file in self.arcnames.items():
                        target_covered_functions = covered_functions.get(orig_file, {})
                        target_function_to_line = function_by_file.get(orig_file, {})
                        target_covered_functions.update({
                            line: 0 for line in set(target_function_to_line.values()).difference(
                                set(target_covered_functions.keys()))})
                        coverage_info.setdefault(arc_file, [])
                        new_cov = {
                            'file name': orig_file,
                            'arcname': arc_file,
                            'total functions': len(target_function_to_line),
                            'covered lines': covered_lines.get(orig_file, {}),
                            'covered functions': target_covered_functions,
                        }
                        if self.collect_functions:
                            new_cov['covered function names'] = \
                                list((name for name, line in target_function_to_line.items()
                                      if target_covered_functions[line] != 0))
                        coverage_info[arc_file].append(new_cov)

        return coverage_info
