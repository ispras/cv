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
# pylint: disable=missing-docstring
"""
Internal representation of witness in CV format.
"""

import json
import os
import re


TAG_HIDE = "hide"
TAG_LEVEL = "level"
TAG_VALUE = "value"


# Capitalize first letters of attribute names.
def capitalize_attr_names(attrs):
    # Each attribute is dictionary with one element which value is either string or array of
    # subattributes.
    for attr in attrs:
        # Does capitalize attribute name.
        attr['name'] = attr['name'][0].upper() + attr['name'][1:]

        if isinstance(attr['value'], list):
            capitalize_attr_names(attr['value'])


class InternalWitness:
    """
    This class keeps witness in CV internal format.
    """
    MODEL_COMMENT_TYPES = 'AUX_FUNC|AUX_FUNC_CALLBACK|MODEL_FUNC|NOTE|ASSERT|ENVIRONMENT_MODEL'
    MAX_COMMENT_LENGTH = 128

    def __init__(self, logger):
        self._attrs = []
        self._edges = []
        self._files = []
        self._funcs = []
        self._logger = logger
        self._entry_node_id = None
        self._model_funcs = {}
        self._spec_funcs = {}
        self._env_models = {}
        self._env_models_json = {}
        self._notes = {}
        self._asserts = {}
        self._actions = []
        self._callback_actions = []
        self.aux_funcs = {}
        self.emg_comments = {}
        self._threads = []
        self.witness_type = None
        self.invariants = {}
        self._warnings = []
        self.is_call_stack = False
        self.is_main_function = False
        self.is_conditions = False
        self.is_notes = False

    @property
    def functions(self):
        return enumerate(self._funcs)

    @property
    def files(self):
        return enumerate(self._files)

    def __get_edge_index(self, edge, default):
        if edge:
            try:
                return self._edges.index(edge)
            except Exception as exception:
                self._logger.warning(f"Cannot get index for edge {edge} due to: {exception}")
                return default
        else:
            return default

    def get_edges(self, start=None, end=None):
        start_index = self.__get_edge_index(start, 0)
        end_index = self.__get_edge_index(end, len(self._edges))
        return self._edges[start_index:end_index]

    def prune(self):
        # pylint: disable=consider-using-set-comprehension
        sink_edges = set([self._edges.index(e) for e in self._edges if e.get('sink')])
        self._edges = [e for index, e in enumerate(self._edges) if index not in sink_edges]

    def serialize(self, remove_prefixes=None):
        capitalize_attr_names(self._attrs)

        files = []
        remove_prefixes_res = []
        if remove_prefixes:
            for prefix in remove_prefixes:
                remove_prefixes_res.append(prefix.lstrip(os.sep))
        for file in self._files:
            res_file = file
            for prefix in remove_prefixes_res:
                res_file = re.sub(prefix, '', res_file)
            res_file = res_file.lstrip(os.sep)
            files.append((file, res_file))

        data = {
            'attrs': self._attrs,
            'edges': self._edges,
            'entry node': 0,
            'files': files,
            'funcs': self._funcs,
            'actions': self._actions,
            'callback actions': self._callback_actions,
            'type': self.witness_type,
            'warnings': self._warnings
        }
        return data

    def add_attr(self, name, value, associate, compare):
        self._attrs.append({
            'name': name,
            'value': value,
            'associate': associate,
            'compare': compare
        })

    def add_entry_node_id(self, node_id):
        self._entry_node_id = node_id

    # noinspection PyUnusedLocal
    def add_edge(self, source, target):
        # pylint: disable=unused-argument
        # TODO: check coherence of source and target.
        edge = {}
        self._edges.append(edge)
        if target in self.invariants:
            edge['invariants'] = self.invariants[target]
        return edge

    def add_file(self, file_name):
        file_name = os.path.normpath(os.path.abspath(file_name))
        if file_name not in self._files:
            if not os.path.isfile(file_name):
                no_file_str = f"There is no file {file_name}"
                self._logger.warning(no_file_str)
                if no_file_str not in self._warnings:
                    self._warnings.append(f"There is no file {file_name}")
                raise FileNotFoundError(f"There is no file {file_name}")
            self._files.append(file_name)
            return self._resolve_file_id(file_name)
        return self._resolve_file_id(file_name)

    def add_function(self, name):
        if name not in self._funcs:
            self._funcs.append(name)
            return len(self._funcs) - 1
        return self.resolve_function_id(name)

    def _add_aux_func(self, identifier, is_callback, formal_arg_names):
        self.aux_funcs[identifier] = {'is callback': is_callback,
                                      'formal arg names': formal_arg_names}

    def _add_emg_comment(self, file, line, data):
        if file not in self.emg_comments:
            self.emg_comments[file] = {}
        self.emg_comments[file][line] = data

    def _resolve_file_id(self, file):
        return self._files.index(file)

    def _resolve_file(self, identifier):
        return self._files[identifier]

    def resolve_function_id(self, name):
        return self._funcs.index(name)

    def add_invariant(self, invariant, node_id):
        self.invariants[node_id] = invariant

    def _resolve_function(self, identifier):
        return self._funcs[identifier]

    def process_comment(self, comment: str) -> str:
        if len(comment) > self.MAX_COMMENT_LENGTH:
            comment = comment[:self.MAX_COMMENT_LENGTH] + "..."
        return comment

    def process_note(self, tag: str, note_str: str) -> tuple:
        # Check for format with note levels
        # Example: level="1" hide="false" value="var = 0"
        if "level=" in note_str and "value=" in note_str:
            match = re.search(rf'{TAG_LEVEL}="(\d)" {TAG_HIDE}="(false|true)" {TAG_VALUE}="(.+)"',
                              note_str)
            if match:
                level, is_hide, value = match.groups()
                level = int(level)
                if is_hide == "true":  # pylint: disable=simplifiable-if-statement
                    is_hide = True
                else:
                    is_hide = False
                value = self.process_comment(value)
                if not level:
                    return "warn", value
                return tag, {
                    TAG_LEVEL: level,
                    TAG_HIDE: is_hide,
                    TAG_VALUE: value
                }
        # Simple format
        return tag if tag == 'note' else 'warn', self.process_comment(note_str)

    def add_model_function(self, func_name: str, comment: str = None):
        if not comment:
            comment = func_name
        func_id = self.add_function(func_name)
        self._model_funcs[func_id] = comment
        self._spec_funcs[func_name] = comment

    def process_verifier_notes(self):
        # Get information from sources.
        self._parse_model_comments()
        self._logger.info('Mark witness with model comments')
        if self._model_funcs or self._notes:
            self.is_notes = True

        warn_edges = []
        for edge in self._edges:
            if 'warn' in edge:
                warn_edges.append(edge['warn'])
            file_id = edge.get('file', None)
            if isinstance(file_id, int):
                file = self._resolve_file(file_id)
            else:
                continue

            start_line = edge.get('start line')

            if 'enter' in edge:
                func_id = edge['enter']
                if func_id in self._model_funcs:
                    note = self._model_funcs[func_id]
                    self._logger.debug(f"Add note {note} for model function "
                                       f"'{self._resolve_function(func_id)}'")
                    edge['note'] = self.process_comment(note)
                if func_id in self._env_models:
                    env_note = self._env_models[func_id]
                    self._logger.debug(f"Add note {env_note} for environment function '"
                                       f"{self._resolve_function(func_id)}'")
                    edge['env'] = self.process_comment(env_note)

            if file_id in self._notes and start_line in self._notes[file_id]:
                note = self._notes[file_id][start_line]
                self._logger.debug(f"Add note {note} for statement from '{file}:{start_line}'")
                edge['note'] = self.process_comment(note)
            elif file_id in self._env_models_json and start_line in self._env_models_json[file_id]:
                env = self._env_models_json[file_id][start_line]
                self._logger.debug(f"Add EMG comment '{env}' for operation from '{file}:{start_line}'")
                edge['env'] = self.process_comment(env)
                del self._env_models_json[file_id][start_line]
            elif file_id in self._asserts and start_line in self._asserts[file_id]:
                warn = self._asserts[file_id][start_line]
                self._logger.debug(f"Add warning {warn} for statement from '{file}:{start_line}'")
                edge['warn'] = self.process_comment(warn)
                warn_edges.append(warn)
            else:
                if 'source' in edge:
                    for spec_func, note in self._spec_funcs.items():
                        if spec_func in edge['source']:
                            edge['note'] = self.process_comment(note)
                            break

        if not warn_edges and self.witness_type == 'violation':
            if self._edges:
                last_edge = self._edges[-1]
                if 'note' in last_edge:
                    last_edge['warn'] = f"Violation of '{self.process_comment(last_edge['note'])}'"
                    del last_edge['note']
                else:
                    last_edge['warn'] = 'Property violation'
        del self._model_funcs, self._notes, self._asserts, self._env_models

    def _parse_model_comments(self):
        self._logger.info('Parse model comments from source files referred by witness')
        emg_comment = re.compile(r'/\*\sLDV\s(.*)\s\*/')
        emg_comment_json = re.compile(r'/\*\sEMG_ACTION\s({.*})\s\*/')

        for file_id, file in self.files:
            if not os.path.isfile(file):
                continue

            self._logger.debug(f'Parse model comments from {file}')

            with open(file, encoding='utf8', errors='ignore') as file_obj:
                line = 0
                for text in file_obj:
                    line += 1

                    # Try match EMG comment
                    # Expect comment like /* TYPE Instance Text */
                    match = emg_comment.search(text)
                    if match:
                        data = json.loads(match.group(1))
                        self._add_emg_comment(file_id, line, data)

                    # Try match JSON EMG comment
                    match = emg_comment_json.search(text)
                    if match:
                        data = json.loads(match.group(1))
                        if "comment" in data:
                            if file_id not in self._env_models_json:
                                self._env_models_json[file_id] = {}
                            self._env_models_json[file_id][line + 1] = data["comment"]
                            # TODO: parse other arguments as well

                    # Match rest comments
                    match = re.search(
                        rf'/\*\s+({self.MODEL_COMMENT_TYPES})\s+(\S+)\s+(.*)\*/', text)
                    if match:
                        kind, func_name, comment = match.groups()

                        comment = comment.rstrip()
                        if kind in ("NOTE", "WARN"):
                            comment = f"{func_name} {comment}"

                            if file_id not in self._notes:
                                self._notes[file_id] = {}
                            self._notes[file_id][line + 1] = comment
                            self._logger.debug(
                                f"Get note '{comment}' for statement from '{file}:{line + 1}'")
                            # Some assertions will become warnings.
                            if kind == 'ASSERT':
                                if file_id not in self._asserts:
                                    self._asserts[file_id] = {}
                                self._asserts[file_id][line + 1] = comment
                                self._logger.debug(f"Get assertion '{comment}' for statement "
                                                   f"from '{file}:{line + 1}'")
                        else:
                            func_name = func_name.rstrip()
                            if not comment:
                                comment = func_name

                            formal_arg_names = []
                            if kind in ('AUX_FUNC', 'AUX_FUNC_CALLBACK'):
                                # Get necessary function declaration located on following line.
                                try:
                                    func_decl = next(file_obj)
                                    # Don't forget to increase counter.
                                    line += 1

                                    # Try to get names for formal arguments (in form "type name")
                                    # that is required for removing auxiliary function calls.
                                    match = re.search(rf'{func_name}\s*\((.+)\)', func_decl)
                                    if match:
                                        formal_args_str = match.group(1)

                                        # Remove arguments of function pointers and braces around
                                        # corresponding argument names.
                                        formal_args_str = re.sub(r'\((.+)\)\(.+\)', r'\g<1>',
                                                                 formal_args_str)

                                        for formal_arg in formal_args_str.split(','):
                                            match = re.search(r'^.*\W+(\w+)\s*$', formal_arg)

                                            # Give up if meet complicated formal argument.
                                            if not match:
                                                formal_arg_names = []
                                                break

                                            formal_arg_names.append(match.group(1))
                                except StopIteration:
                                    self._logger.warning(
                                        'Auxiliary function definition does not exist')
                                    continue

                            # Deal with functions referenced by witness.
                            try:
                                func_id = self.resolve_function_id(func_name)
                            except ValueError:
                                self.add_function(func_name)
                                func_id = self.resolve_function_id(func_name)

                            if kind == 'AUX_FUNC':
                                self._add_aux_func(func_id, False, formal_arg_names)
                                self._logger.debug(
                                    f"Get auxiliary function '{func_name}' from '{file}:{line}'")
                            elif kind == 'AUX_FUNC_CALLBACK':
                                self._add_aux_func(func_id, True, formal_arg_names)
                                self._logger.debug(f"Get auxiliary function '{func_name}' for "
                                                   f"callback from '{file}:{line}'")
                            elif kind == 'ENVIRONMENT_MODEL':
                                self._env_models[func_id] = comment
                                self._logger.debug(f"Get environment model '{comment}' for "
                                                   f"function '{func_name}' from '{file}:{line}'")
                            else:
                                self._model_funcs[func_id] = comment
                                self._logger.debug(f"Get note '{comment}' for model function "
                                                   f"'{func_name}' from '{file}:{line}'")

    def add_thread(self, thread_id: str):
        self._threads.append(thread_id)

    def final_checks(self, entry_point="main"):
        # Check for warnings
        if self.witness_type == 'violation':
            if not self.is_call_stack:
                self._warnings.append('No call stack (please add tags "enterFunction" and '
                                      '"returnFrom" to improve visualization)')
            if not self.is_conditions:
                self._warnings.append(
                    'No conditions (please add tags "control" to improve visualization)')
            if not self.is_main_function and self._edges:
                self._warnings.append('No entry point (entry point call was generated)')
                entry_elem = {
                    'enter': self.add_function(entry_point),
                    'start line': 0,
                    'file': 0,
                    'entry_point': 'entry point',
                    'source': f"{entry_point}()"
                }
                if not self._threads:
                    entry_elem['thread'] = '1'
                else:
                    entry_elem['thread'] = str(self._threads[0])
                self._edges.insert(0, entry_elem)
            # if not self.is_notes:
            #     self._warnings.append(
            #         'Optional: no violation hints (please add tags "note" and "warn" to '
            #         'improve visualization)')
        if not self._threads:
            is_main_process = False
            for edge in self._edges:
                if not is_main_process and 'enter' in edge:
                    is_main_process = True
                if is_main_process:
                    edge['thread'] = '1'
                else:
                    edge['thread'] = '0'

    def get_func_name(self, identifier: int):
        return self._funcs[identifier]

    def get_file_name(self, identifier: int):
        if self._files:
            return self._files[identifier]
        return None
