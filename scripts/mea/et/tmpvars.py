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
Contains specific simplifications of violation witnesses for visualization.
"""

import re


def generic_simplifications(logger, trace):
    """
    Performs all simplifications
    """
    logger.info('Simplify error trace')
    _basic_simplification(trace)
    _remove_switch_cases(logger, trace)
    trace.prune()


def _basic_simplification(error_trace):
    # Remove all edges without source attribute. Otherwise visualization will be very poor.
    for edge in error_trace.get_edges():
        source_line = edge.get('source', "")
        if not source_line:
            # Now we do need source code to be presented with all edges.
            edge['sink'] = True

        # Make source code more human readable.
        # Remove all broken indentations - error traces visualizer will add its own ones but
        # will do this in much more attractive way.
        source_line = re.sub(r'[ \t]*\n[ \t]*', ' ', source_line)

        # Remove "[...]" around conditions.
        if 'condition' in edge:
            source_line = source_line.strip('[]')

        # Get rid of continues whitespaces.
        source_line = re.sub(r'[ \t]+', ' ', source_line)

        # Remove space before trailing ";".
        source_line = re.sub(r' ;$', ';', source_line)

        # Remove space before "," and ")".
        source_line = re.sub(r' (,\|\))', r'\g<1>', source_line)

        # Replace "!(... ==/!=/<=/>=/</> ...)" with "... !=/==/>/</>=/<= ...".
        cond_replacements = {'==': '!=', '!=': '==', '<=': '>', '>=': '<', '<': '>=', '>': '<='}
        for orig_cond, replacement_cond in cond_replacements.items():
            res = re.match(rf'^!\((.+) {orig_cond} (.+)\)$', source_line)
            if res:
                source_line = f'{res.group(1)} {replacement_cond} {res.group(2)}'
                # Do not proceed after some replacement is applied - others won't be done.
                break

        # Remove unnessary "(...)" around returned values/expressions.
        source_line = re.sub(r'^return \((.*)\);$', r'return \g<1>;', source_line)

        # Make source code and assumptions more human readable (common improvements).
        for source_kind in ('source', 'assumption'):
            if source_kind in edge:
                # Remove unnessary "(...)" around integers.
                edge[source_kind] = re.sub(r' \((-?\d+\w*)\)', r' \g<1>', edge[source_kind])

                # Replace "& " with "&".
                edge[source_kind] = re.sub(r'& ', '&', edge[source_kind])
        if source_line == "1" or source_line == "\"\"":
            edge['sink'] = True
        edge['source'] = source_line


def _remove_switch_cases(logger, error_trace):
    # Get rid of redundant switch cases. Replace:
    #   assume(var != A)
    #   assume(var != B)
    #   ...
    #   assume(var == Z)
    # with:
    #   assume(var == Z)
    removed_switch_cases_num = 0
    for edge in error_trace.get_edges():
        # Begin to match pattern just for edges that represent conditions.
        if 'condition' not in edge:
            continue

        # Get all continues conditions.
        cond_edges = []
        for cond_edge in error_trace.get_edges(start=edge):
            if 'condition' not in cond_edge:
                break
            cond_edges.append(cond_edge)

        # Do not proceed if there is not continues conditions.
        if len(cond_edges) == 1:
            continue

        var = None
        start_idx = 0
        cond_edges_to_remove = []
        for idx, cond_edge in enumerate(cond_edges):
            res = re.search(r'^(.+) ([=!]=)', cond_edge['source'])

            # Start from scratch if meet unexpected format of condition.
            if not res:
                var = None
                continue

            # Do not proceed until first condition matches pattern.
            if var is None and res.group(2) != '!=':
                continue

            # Begin to collect conditions.
            if var is None:
                start_idx = idx
                var = res.group(1)
                continue
            # Start from scratch if first expression condition differs.
            elif var != res.group(1):
                var = None
                continue

            # Finish to collect conditions. Pattern matches.
            if var is not None and res.group(2) == '==':
                cond_edges_to_remove.extend(cond_edges[start_idx:idx])
                var = None
                continue

        for cond_edge in reversed(cond_edges_to_remove):
            if not cond_edge.get('sink'):
                cond_edge['sink'] = True
                removed_switch_cases_num += 1

    if removed_switch_cases_num:
        logger.debug(f'{removed_switch_cases_num} switch cases were removed')
