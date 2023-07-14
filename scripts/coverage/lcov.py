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
import json
import os
import re


# TODO: refactor this

def add_to_coverage(merged_coverage_info, coverage_info):
    for file_name in coverage_info:
        merged_coverage_info.setdefault(file_name, {
            'total functions': coverage_info[file_name][0]['total functions'],
            'covered lines': dict(),
            'covered functions': dict(),
            'covered function names': list()
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


def get_coverage(merged_coverage_info):
    # Map combined coverage to the required format
    line_coverage = dict()
    function_coverage = dict()
    function_statistics = dict()
    function_name_staticitcs = dict()

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
            function_name_staticitcs[file_name] = list(merged_coverage_info[file_name]['covered function names'])
    function_name_staticitcs['overall'] = None

    # Merge covered lines into the range
    for key, value in line_coverage.items():
        for file_name, lines in value.items():
            line_coverage[key][file_name] = __build_ranges(lines)

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


def make_relative_path(dirs, file_or_dir, absolutize=False):
    # Normalize paths first of all.
    dirs = [os.path.normpath(d) for d in dirs]
    file_or_dir = os.path.normpath(file_or_dir)

    # Check all dirs are absolute or relative.
    is_dirs_abs = False
    if all(os.path.isabs(d) for d in dirs):
        is_dirs_abs = True
    elif all(not os.path.isabs(d) for d in dirs):
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
    for d in sorted(dirs, key=lambda t: len(t), reverse=True):
        if os.path.commonpath([file_or_dir, d]) == d:
            return os.path.relpath(file_or_dir, d)

    return file_or_dir


class LCOV:
    NEW_FILE_PREFIX = "TN:"
    EOR_PREFIX = "end_of_record"
    FILENAME_PREFIX = "SF:"
    LINE_PREFIX = "DA:"
    FUNCTION_PREFIX = "FNDA:"
    FUNCTION_NAME_PREFIX = "FN:"
    PARIALLY_ALLOWED_EXT = ('.c', '.i', '.c.aux')

    def __init__(self, logger, coverage_file, clade_dir, source_dirs, search_dirs, main_work_dir, completeness,
                 coverage_id=None, coverage_info_dir=None, collect_functions=True, ignore_files=None,
                 default_file=None):
        # Public
        self.logger = logger
        self.coverage_file = coverage_file
        self.clade_dir = clade_dir
        self.source_dirs = [os.path.normpath(p) for p in source_dirs]
        self.search_dirs = [os.path.normpath(p) for p in search_dirs]
        self.main_work_dir = main_work_dir
        self.completeness = completeness
        self.coverage_info_dir = coverage_info_dir
        self.arcnames = {}
        self.collect_functions = collect_functions
        if ignore_files is None:
            ignore_files = set()
        self.ignore_files = ignore_files
        self.default_file = default_file

        # Sanity checks
        if self.completeness not in ('full', 'partial', 'lightweight', 'none', None):
            raise NotImplementedError("Coverage type {!r} is not supported".format(self.completeness))

        # Import coverage
        try:
            if self.completeness in ('full', 'partial', 'lightweight'):
                self.coverage_info = self.parse()

                if coverage_id:
                    with open(coverage_id, 'w', encoding='utf-8') as fp:
                        json.dump(self.coverage_info, fp, ensure_ascii=True, sort_keys=True, indent="\t")

                coverage = {}
                add_to_coverage(coverage, self.coverage_info)
                with open('coverage.json', 'w', encoding='utf-8') as fp:
                    json.dump(get_coverage(coverage), fp, ensure_ascii=True, sort_keys=True, indent=None)
        except Exception:
            if os.path.isfile('coverage.json'):
                os.remove('coverage.json')
            raise

    def parse(self) -> dict:
        dir_map = (
            ('sources', self.source_dirs),
            ('specifications', (
                os.path.normpath(os.path.join(self.main_work_dir, 'job', 'root', 'specifications')),
            )),
            ('generated', (
                os.path.normpath(self.main_work_dir),
            ))
        )

        ignore_file = False

        if not os.path.isfile(self.coverage_file):
            raise Exception('There is no coverage file {0}'.format(self.coverage_file))

        # Gettings dirs, that should be excluded.
        excluded_dirs = set()
        if self.completeness in ('partial', 'lightweight'):
            with open(self.coverage_file, encoding='utf-8') as fp:
                # Build map, that contains dir as key and list of files in the dir as value
                all_files = {}
                for line in fp:
                    line = line.rstrip('\n')
                    if line.startswith(self.FILENAME_PREFIX):
                        file_name = line[len(self.FILENAME_PREFIX):]
                        file_name = os.path.normpath(file_name)
                        if os.path.isfile(file_name):
                            path, file = os.path.split(file_name)
                            # All pathes should be absolute, otherwise we cannot match source dirs later
                            path = os.path.join(os.path.sep, make_relative_path([self.clade_dir], path))
                            all_files.setdefault(path, [])
                            all_files[path].append(file)

                for path, files in all_files.items():
                    # Lightweight coverage keeps only source code dirs.
                    if self.completeness == 'lightweight' and \
                            all(os.path.commonpath([s, path]) != s for s in self.source_dirs):
                        self.logger.debug('Excluded {0}'.format(path))
                        excluded_dirs.add(path)
                        continue
                    # Partial coverage keeps only dirs, that contains source files.
                    for file in files:
                        if file.endswith('.c') or file.endswith('.c.aux'):
                            break
                    else:
                        excluded_dirs.add(path)

        # Parsing coverage file
        coverage_info = {}
        with open(self.coverage_file, encoding='utf-8') as fp:
            count_covered_functions = None
            for line in fp:
                line = line.rstrip('\n')

                if ignore_file and not line.startswith(self.FILENAME_PREFIX):
                    continue

                if line.startswith(self.NEW_FILE_PREFIX):
                    # Clean
                    file_name = None
                    covered_lines = {}
                    function_to_line = {}
                    covered_functions = {}
                    count_covered_functions = 0
                elif line.startswith(self.FILENAME_PREFIX):
                    # Get file name, determine his directory and determine, should we ignore this
                    real_file_name = line[len(self.FILENAME_PREFIX):]
                    real_file_name = os.path.normpath(real_file_name)
                    if self.default_file:
                        # TODO: dirty workaround (required for specific cases).
                        dw_name = re.sub(r'.+/vcloud-\S+/worker/working_dir_[^/]+/', '', real_file_name)
                        real_file_name = self.default_file
                        for source_dir in self.source_dirs:
                            for tmp_file_name in [self.default_file, dw_name]:
                                tmp_file_name = os.path.join(source_dir, tmp_file_name)
                                if os.path.exists(tmp_file_name):
                                    real_file_name = tmp_file_name
                                    break
                    file_name = os.path.join(os.path.sep,
                                             make_relative_path([self.clade_dir], real_file_name))
                    if os.path.isfile(real_file_name) and \
                            all(os.path.commonpath((p, file_name)) != p for p in excluded_dirs):
                        for dest, srcs in dir_map:
                            for src in srcs:
                                if os.path.commonpath([real_file_name, src]) != src:
                                    continue
                                if dest == 'generated' or dest == 'specifications':
                                    new_file_name = os.path.join(dest, os.path.basename(file_name))
                                else:
                                    new_file_name = os.path.join(dest, os.path.relpath(file_name, src))

                                if new_file_name in self.ignore_files:
                                    continue
                                ignore_file = False
                                break
                            else:
                                continue
                            break
                        # This "else" corresponds "for"
                        else:
                            # Check other prefixes
                            new_file_name = make_relative_path(self.search_dirs, file_name)
                            if new_file_name == file_name:
                                ignore_file = True
                                continue
                            else:
                                ignore_file = False
                            new_file_name = os.path.join('specifications', new_file_name)

                        self.arcnames[real_file_name] = new_file_name
                        old_file_name, file_name = real_file_name, new_file_name
                    else:
                        ignore_file = True
                elif line.startswith(self.LINE_PREFIX):
                    # Coverage of the specified line
                    splts = line[len(self.LINE_PREFIX):].split(',')
                    covered_lines[int(splts[0])] = int(splts[1])
                elif line.startswith(self.FUNCTION_NAME_PREFIX):
                    # Mapping of the function name to the line number
                    splts = line[len(self.FUNCTION_NAME_PREFIX):].split(',')
                    function_to_line.setdefault(splts[1], 0)
                    function_to_line[splts[1]] = int(splts[0])
                elif line.startswith(self.FUNCTION_PREFIX):
                    # Coverage of the specified function
                    splts = line[len(self.FUNCTION_PREFIX):].split(',')
                    if splts[0] == "0":
                        continue
                    covered_functions[function_to_line[splts[1]]] = int(splts[0])
                    count_covered_functions += 1
                elif line.startswith(self.EOR_PREFIX):
                    # End coverage for the specific file

                    # Add not covered functions
                    covered_functions.update({line: 0 for line in set(function_to_line.values())
                                             .difference(set(covered_functions.keys()))})

                    coverage_info.setdefault(file_name, [])

                    new_cov = {
                        'file name': old_file_name,
                        'arcname': file_name,
                        'total functions': len(function_to_line),
                        'covered lines': covered_lines,
                        'covered functions': covered_functions
                    }
                    if self.collect_functions:
                        new_cov['covered function names'] = list((name for name, line in function_to_line.items()
                                                                  if covered_functions[line] != 0))
                    coverage_info[file_name].append(new_cov)

        return coverage_info
