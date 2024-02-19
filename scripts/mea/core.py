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
This library presents core functions for MEA, such as conversion and comparison of error traces.
"""

# pylint: disable=invalid-name, consider-iterating-dictionary

import operator
import re


# Conversion functions.
CONVERSION_FUNCTION_CALL_TREE = "call tree"
CONVERSION_FUNCTION_MODEL_FUNCTIONS = "model functions"
CONVERSION_FUNCTION_CONDITIONS = "conditions"
CONVERSION_FUNCTION_ASSIGNMENTS = "assignments"
CONVERSION_FUNCTION_NOTES = "error descriptions"
CONVERSION_FUNCTION_FULL = "full"
DEFAULT_CONVERSION_FUNCTION = CONVERSION_FUNCTION_MODEL_FUNCTIONS
CACHED_CONVERSION_FUNCTIONS = [
    CONVERSION_FUNCTION_CALL_TREE,
    CONVERSION_FUNCTION_MODEL_FUNCTIONS,
    CONVERSION_FUNCTION_NOTES]

# Comparison functions.
COMPARISON_FUNCTION_EQUAL = "equal"
COMPARISON_FUNCTION_INCLUDE = "include"
COMPARISON_FUNCTION_INCLUDE_WITH_ERROR = "include with error"
COMPARISON_FUNCTION_INCLUDE_PARTIAL = "partial include"
COMPARISON_FUNCTION_INCLUDE_PARTIAL_ORDERED = "partial include ordered"
COMPARISON_FUNCTION_SKIP = "skip"
DEFAULT_COMPARISON_FUNCTION = COMPARISON_FUNCTION_EQUAL

# Tags for configurations.
TAG_CONVERSION_FUNCTION = "conversion_function"
TAG_COMPARISON_FUNCTION = "comparison_function"
TAG_EDITED_ERROR_TRACE = "edited_error_trace"

# Conversion fucntions arguments.
TAG_ADDITIONAL_MODEL_FUNCTIONS = "additional_model_functions"
TAG_NOTES_LEVEL = "notes_level"
TAG_FILTERED_MODEL_FUNCTIONS = "filtered_model_functions"
TAG_USE_NOTES = "use_notes"
TAG_USE_WARNS = "use_warns"
TAG_IGNORE_NOTES_TEXT = "ignore_notes_text"

# Converted error trace tags.
CET_OP = "op"
CET_OP_CALL = "CALL"
CET_OP_RETURN = "RET"
CET_OP_ASSUME = "ASSUME"
CET_OP_ASSIGN = "ASSIGN"
CET_OP_NOTE = "NOTE"
CET_OP_WARN = "WARN"
CET_THREAD = "thread"
CET_SOURCE = "source"
CET_DISPLAY_NAME = "name"
CET_ID = "id"
CET_LINE = "line"
ASSIGN_MARK = " = "

DEFAULT_NOTES_LEVEL = 1
DEFAULT_SIMILARITY_THRESHOLD = 100  # in % (all threads are equal)
DEFAULT_PROPERTY_CHECKS_TEXT = "property check description"


def convert_error_trace(error_trace: dict, conversion_function: str, args: dict = dict) -> list:
    """
    Convert json error trace into internal representation (list of selected elements).
    """
    functions = {
        CONVERSION_FUNCTION_MODEL_FUNCTIONS: __convert_model_functions,
        CONVERSION_FUNCTION_CALL_TREE: __convert_call_tree_filter,
        CONVERSION_FUNCTION_CONDITIONS: __convert_conditions,
        CONVERSION_FUNCTION_FULL: __convert_full,
        CONVERSION_FUNCTION_ASSIGNMENTS: __convert_assignments,
        CONVERSION_FUNCTION_NOTES: __convert_notes
    }
    if conversion_function not in functions.keys():
        conversion_function = DEFAULT_CONVERSION_FUNCTION
    result = functions[conversion_function](error_trace, args)

    if (args.get(TAG_USE_NOTES, args.get(TAG_USE_WARNS, False)) or
            args.get(TAG_IGNORE_NOTES_TEXT, False)) and \
            conversion_function not in [CONVERSION_FUNCTION_FULL, CONVERSION_FUNCTION_NOTES]:
        result += __convert_notes(error_trace, args)
        result = sorted(result, key=operator.itemgetter(CET_ID))

    filtered_functions = set(args.get(TAG_FILTERED_MODEL_FUNCTIONS, []))
    if filtered_functions:
        result = __filter_functions(result, filtered_functions)

    return result


def is_equivalent(comparison_results: float, similarity_threshold: int) -> bool:
    """
    Returns true, if compared error traces are considered to be equivalent in terms of
    specified threshold.
    """
    return comparison_results and (comparison_results * 100 >= similarity_threshold)


def compare_error_traces(edited_error_trace: list, compared_error_trace: list,
                         comparison_function: str) -> float:
    """
    Compare two error traces by means of specified function and return similarity coefficient
    for their threads equivalence (in case of a single thread function returns True/False).
    """
    et1_threaded, et2_threaded = __transform_to_threads(edited_error_trace, compared_error_trace)
    if not et1_threaded and not et2_threaded:
        # Return true for empty converted error traces (so they will be applied to all
        # reports with the same attributes)
        return 1.0
    functions = {
        COMPARISON_FUNCTION_EQUAL: __compare_equal,
        COMPARISON_FUNCTION_INCLUDE: __compare_include,
        COMPARISON_FUNCTION_INCLUDE_WITH_ERROR: __compare_include_with_error,
        COMPARISON_FUNCTION_INCLUDE_PARTIAL: __compare_include_partial,
        COMPARISON_FUNCTION_INCLUDE_PARTIAL_ORDERED: __compare_include_partial_ordered,
        COMPARISON_FUNCTION_SKIP: __compare_skip
    }
    if comparison_function not in functions.keys():
        comparison_function = DEFAULT_COMPARISON_FUNCTION
    equal_threads = functions[comparison_function](et1_threaded, et2_threaded)
    equal_threads = min(equal_threads, len(et1_threaded), len(et2_threaded))
    return __get_similarity_coefficient(et1_threaded, et2_threaded, equal_threads)


# noinspection PyUnusedLocal
def __convert_call_tree_filter(error_trace: dict, args: dict = None) -> list:
    # pylint: disable=unused-argument
    converted_error_trace = []
    counter = 0
    # TODO: check this in core (one node for call and return edges).
    double_funcs = {}
    for edge in error_trace['edges']:
        if 'entry_point' in edge:
            continue
        if 'enter' in edge and 'return' in edge:
            double_funcs[edge['enter']] = edge['return']
        if 'enter' in edge:
            function_call = error_trace['funcs'][edge['enter']]
            converted_error_trace.append({
                CET_OP: CET_OP_CALL,
                CET_THREAD: edge['thread'],
                CET_SOURCE: edge['source'],
                CET_LINE: edge['start line'],
                CET_DISPLAY_NAME: function_call,
                CET_ID: counter
            })
        elif 'return' in edge:
            function_return = error_trace['funcs'][edge['return']]
            converted_error_trace.append({
                CET_OP: CET_OP_RETURN,
                CET_THREAD: edge['thread'],
                CET_LINE: edge['start line'],
                CET_SOURCE: edge['source'],
                CET_DISPLAY_NAME: function_return,
                CET_ID: counter
            })
            double_return = edge['return']
            while True:
                if double_return in double_funcs.keys():
                    converted_error_trace.append({
                        CET_OP: CET_OP_RETURN,
                        CET_THREAD: edge['thread'],
                        CET_LINE: edge['start line'],
                        CET_SOURCE: edge['source'],
                        CET_DISPLAY_NAME: error_trace['funcs'][double_funcs[double_return]],
                        CET_ID: counter
                    })
                    tmp = double_return
                    double_return = double_funcs[double_return]
                    del double_funcs[tmp]
                else:
                    break
        counter += 1
    return converted_error_trace


def __convert_model_functions(error_trace: dict, args: dict = None) -> list:
    if args is None:
        args = {}
    model_functions = __get_model_functions(error_trace, args)
    converted_error_trace = __convert_call_tree_filter(error_trace, args)
    removed_indexes = set()
    thread_start_indexes = set()
    cur_thread = -1
    for counter, item in enumerate(converted_error_trace):
        op = item[CET_OP]
        thread = item[CET_THREAD]
        name = item[CET_DISPLAY_NAME]
        if cur_thread != thread:
            thread_start_indexes.add(counter)
            cur_thread = thread
        if counter in removed_indexes:
            continue
        if op == CET_OP_CALL:
            is_save = False
            remove_items = 0
            for checking_elem in converted_error_trace[counter:]:
                remove_items += 1
                checking_op = checking_elem[CET_OP]
                checking_name = checking_elem[CET_DISPLAY_NAME]
                checking_thread = checking_elem[CET_THREAD]
                if checking_op == CET_OP_RETURN and checking_name == name:
                    break
                if checking_thread != thread:
                    remove_items -= 1
                    break
                if checking_op == CET_OP_CALL:
                    if checking_name in model_functions:
                        is_save = True
                        break
            if not is_save:
                for index in range(counter, counter + remove_items):
                    removed_indexes.add(index)
    resulting_error_trace = []
    for counter, item in enumerate(converted_error_trace):
        if counter not in removed_indexes or counter in thread_start_indexes:
            resulting_error_trace.append(item)
    return resulting_error_trace


def __filter_functions(converted_error_trace: list, filtered_functions: set) -> list:
    result = []
    filtered_stack = []
    cur_thread = None
    for item in converted_error_trace:
        op = item[CET_OP]
        thread = item[CET_THREAD]
        name = item[CET_DISPLAY_NAME]
        if cur_thread and not cur_thread == thread:
            filtered_stack.clear()
        if name in filtered_functions:
            if op == CET_OP_CALL:
                filtered_stack.append(name)
                cur_thread = thread
            elif op == CET_OP_RETURN:
                if filtered_stack:
                    filtered_stack.pop()
        elif not filtered_stack:
            result.append(item)
    return result


# noinspection PyUnusedLocal
def __convert_conditions(error_trace: dict, args: dict = None) -> list:
    # pylint: disable=unused-argument
    converted_error_trace = []
    counter = 0
    for edge in error_trace['edges']:
        if 'condition' in edge:
            assume = edge['condition']
            converted_error_trace.append({
                CET_OP: CET_OP_ASSUME,
                CET_THREAD: edge['thread'],
                CET_SOURCE: edge['source'],
                CET_LINE: edge['start line'],
                CET_DISPLAY_NAME: assume,
                CET_ID: counter
            })
        counter += 1
    return converted_error_trace


# noinspection PyUnusedLocal
def __convert_assignments(error_trace: dict, args: dict = None) -> list:
    # pylint: disable=unused-argument
    converted_error_trace = []
    counter = 0
    for edge in error_trace['edges']:
        if 'source' in edge:
            source = edge['source']
            if ASSIGN_MARK in source:
                converted_error_trace.append({
                    CET_OP: CET_OP_ASSIGN,
                    CET_THREAD: edge['thread'],
                    CET_SOURCE: edge['source'],
                    CET_LINE: edge['start line'],
                    CET_DISPLAY_NAME: source,
                    CET_ID: counter
                })
        counter += 1
    return converted_error_trace


def __convert_notes(error_trace: dict, args=None) -> list:
    if args is None:
        args = {}
    converted_error_trace = []
    counter = 0
    use_notes = args.get(TAG_USE_NOTES, False)
    use_warns = args.get(TAG_USE_WARNS, False)
    ignore_text = args.get(TAG_IGNORE_NOTES_TEXT, False)
    if not use_notes and not use_warns:
        # Ignore, since we need at least one flag as True.
        use_notes = True
        use_warns = True

    for edge in error_trace['edges']:
        text = DEFAULT_PROPERTY_CHECKS_TEXT
        if 'note' in edge:
            if not ignore_text:
                text = edge['note']
                note_desc = edge['note']
                if isinstance(note_desc, dict):
                    text = note_desc.get('value', note_desc)
            if use_notes:
                converted_error_trace.append({
                    CET_OP: CET_OP_NOTE,
                    CET_THREAD: edge['thread'],
                    CET_SOURCE: edge['source'],
                    CET_LINE: edge['start line'],
                    CET_DISPLAY_NAME: text,
                    CET_ID: counter
                })
        elif 'warn' in edge:
            if not ignore_text:
                text = edge['warn']
            if use_warns:
                converted_error_trace.append({
                    CET_OP: CET_OP_WARN,
                    CET_THREAD: edge['thread'],
                    CET_SOURCE: edge['source'],
                    CET_LINE: edge['start line'],
                    CET_DISPLAY_NAME: text,
                    CET_ID: counter
                })
        counter += 1
    return converted_error_trace


# noinspection PyUnusedLocal
def __convert_full(error_trace: dict, args: dict = None) -> list:
    # pylint: disable=unused-argument
    converted_error_trace = __convert_call_tree_filter(error_trace, args) + \
                            __convert_conditions(error_trace, args) + \
                            __convert_assignments(error_trace, args) + \
                            __convert_notes(error_trace, args)
    converted_error_trace = sorted(converted_error_trace, key=operator.itemgetter(CET_ID))
    return converted_error_trace


def __get_model_functions(error_trace: dict, args: dict) -> set:
    """
    Extract model functions from error trace.
    """
    stack = []
    additional_model_functions = set(args.get(TAG_ADDITIONAL_MODEL_FUNCTIONS, []))
    notes_level = int(args.get(TAG_NOTES_LEVEL, DEFAULT_NOTES_LEVEL))
    model_functions = additional_model_functions
    patterns = set()
    for func in model_functions:
        if not str(func).isidentifier():
            patterns.add(func)
    for edge in error_trace['edges']:
        if 'enter' in edge:
            func = error_trace['funcs'][edge['enter']]
            if patterns:
                for pattern_func in patterns:
                    if re.match(pattern_func, func):
                        model_functions.add(func)
            stack.append(func)
        if 'return' in edge:
            # func = error_trace['funcs'][edge['return']]
            if stack:
                stack.pop()
        if stack:
            if 'warn' in edge:
                model_functions.add(stack[len(stack) - 1])
            if 'note' in edge:
                note_desc = edge['note']
                is_add = True
                if isinstance(note_desc, dict):
                    level = int(note_desc.get('level', 1))
                    if level > notes_level:
                        is_add = False
                if is_add:
                    model_functions.add(stack[len(stack) - 1])

    model_functions = model_functions - patterns
    return model_functions


def __prep_elem_for_cmp(elem: dict, error_trace: dict) -> None:
    op = elem[CET_OP]
    thread = elem[CET_THREAD]
    if thread not in error_trace:
        error_trace[thread] = []
    if op in [CET_OP_RETURN, CET_OP_CALL]:
        error_trace[thread].append((op, elem[CET_DISPLAY_NAME]))
    elif op == CET_OP_ASSUME:
        thread_aux = f"{thread}_aux"
        if thread_aux not in error_trace:
            error_trace[thread_aux] = []
        error_trace[thread_aux].append((op, elem[CET_DISPLAY_NAME], elem[CET_SOURCE]))
    elif op in [CET_OP_WARN, CET_OP_NOTE, CET_OP_ASSIGN]:
        thread_aux = f"{thread}_aux"
        if thread_aux not in error_trace:
            error_trace[thread_aux] = []
        error_trace[thread_aux].append((op, elem[CET_DISPLAY_NAME]))


def __transform_to_threads(edited_error_trace: list, compared_error_trace: list) -> (dict, dict):
    et1 = {}
    et2 = {}
    for et_elem in edited_error_trace:
        __prep_elem_for_cmp(et_elem, et1)
    for et_elem in compared_error_trace:
        __prep_elem_for_cmp(et_elem, et2)
    et1_threaded = {}
    et2_threaded = {}
    for thread, trace in et1.items():
        if trace:
            et1_threaded[thread] = tuple(trace)
    for thread, trace in et2.items():
        if trace:
            et2_threaded[thread] = tuple(trace)
    return et1_threaded, et2_threaded


def __sublist(sublist: tuple, big_list: tuple) -> bool:
    """
    Check that list sublist is included into the list big_list.
    """
    sublist = ",".join(str(v) for v in sublist)
    big_list = ",".join(str(v) for v in big_list)
    return sublist in big_list


def __compare_skip(edited_error_trace: dict, compared_error_trace: dict) -> int:
    return min(len(edited_error_trace), len(compared_error_trace))


def __compare_equal(edited_error_trace: dict, compared_error_trace: dict) -> int:
    result = {}
    for id_1, thread_1 in edited_error_trace.items():
        for id_2, thread_2 in compared_error_trace.items():
            if thread_1 == thread_2:
                if id_1 not in result:
                    result[id_1] = []
                result[id_1].append(id_2)
    return __convert_to_number_of_compared_threads(result)


def __compare_include(edited_error_trace: dict, compared_error_trace: dict) -> int:
    result = {}
    for id_1, thread_1 in edited_error_trace.items():
        for id_2, thread_2 in compared_error_trace.items():
            if __sublist(thread_1, thread_2):
                if id_1 not in result:
                    result[id_1] = []
                result[id_1].append(id_2)
    return __convert_to_number_of_compared_threads(result)


def __compare_include_with_error(edited_error_trace: dict, compared_error_trace: dict) -> int:
    for cet in [edited_error_trace, compared_error_trace]:
        for thread, trace in cet.items():
            cet[thread] = trace + (('WARN', ''), )
    return __compare_include(edited_error_trace, compared_error_trace)


def __convert_to_number_of_compared_threads(result: dict) -> int:
    used_transitions = set()
    max_number_of_threads = 0
    while True:
        used_ids_2 = set()
        number_of_threads = 0
        for id_1, ids_2 in result.items():
            for id_2 in ids_2:
                id_str = f"{id_1}_{id_2}"
                if id_2 not in used_ids_2 and id_str not in used_transitions:
                    used_ids_2.add(id_2)
                    used_transitions.add(id_str)
                    number_of_threads += 1
                    break
        if number_of_threads > max_number_of_threads:
            max_number_of_threads = number_of_threads

        if number_of_threads == 0:
            break
    return max_number_of_threads


def __compare_include_partial(edited_error_trace: dict, compared_error_trace: dict) -> int:
    result = {}
    for id_1, thread_1 in edited_error_trace.items():
        for id_2, thread_2 in compared_error_trace.items():
            if all(elem in thread_2 for elem in thread_1):
                if id_1 not in result:
                    result[id_1] = []
                result[id_1].append(id_2)
    return __convert_to_number_of_compared_threads(result)


def __compare_include_partial_ordered(edited_error_trace: dict, compared_error_trace: dict) -> int:
    result = {}
    for id_1, thread_1 in edited_error_trace.items():
        for id_2, thread_2 in compared_error_trace.items():
            last_index = 0
            is_eq = True
            for elem in thread_1:
                if elem in thread_2[last_index:]:
                    last_index = thread_2.index(elem)
                else:
                    is_eq = False
                    break
            if is_eq:
                if id_1 not in result:
                    result[id_1] = []
                result[id_1].append(id_2)
    return __convert_to_number_of_compared_threads(result)


def __get_similarity_coefficient(et_threaded_1: dict, et_threaded_2: dict, common_elements: int) \
        -> float:
    # Currently represented only as Jaccard index.
    diff_elements = len(et_threaded_1) + len(et_threaded_2) - common_elements
    if diff_elements:
        return round(common_elements / diff_elements, 2)
    return 0.0
