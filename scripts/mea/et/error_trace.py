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

import re
import os
import json


# Capitalize first letters of attribute names.
def capitalize_attr_names(attrs):
    # Each attribute is dictionary with one element which value is either string or array of subattributes.
    for attr in attrs:
        # Does capitalize attribute name.
        attr['name'] = attr['name'][0].upper() + attr['name'][1:]

        if isinstance(attr['value'], list):
            capitalize_attr_names(attr['value'])


class ErrorTrace:
    MODEL_COMMENT_TYPES = 'AUX_FUNC|AUX_FUNC_CALLBACK|MODEL_FUNC|NOTE|ASSERT|ENVIRONMENT_MODEL'
    MAX_COMMENT_LENGTH = 128

    def __init__(self, logger):
        self._attrs = list()
        self._edges = list()
        self._files = list()
        self._funcs = list()
        self._logger = logger
        self._entry_node_id = None
        self._model_funcs = dict()
        self._spec_funcs = dict()
        self._env_models = dict()
        self._notes = dict()
        self._asserts = dict()
        self._actions = list()
        self._callback_actions = list()
        self.aux_funcs = dict()
        self.emg_comments = dict()
        self._threads = list()
        self.witness_type = None
        self.invariants = dict()
        self._warnings = list()
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
            except Exception as e:
                self._logger.warning("Cannot get index for edge {} due to: ".format(edge, e))
                return default
        else:
            return default

    def get_edges(self, start=None, end=None):
        start_index = self.__get_edge_index(start, 0)
        end_index = self.__get_edge_index(end, len(self._edges))
        return self._edges[start_index:end_index]

    def prune(self):
        sink_edges = set([self._edges.index(e) for e in self._edges if e.get('sink')])
        self._edges = [e for index, e in enumerate(self._edges) if index not in sink_edges]

    def serialize(self):
        capitalize_attr_names(self._attrs)

        data = {
            'attrs': self._attrs,
            'edges': self._edges,
            'entry node': 0,
            'files': self._files,
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

    def add_edge(self, source, target):
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
                no_file_str = "There is no file {!r}".format(file_name)
                self._logger.warning(no_file_str)
                if no_file_str not in self._warnings:
                    self._warnings.append("There is no file {!r}".format(file_name))
                raise FileNotFoundError
            self._files.append(file_name)
            return self.resolve_file_id(file_name)
        else:
            return self.resolve_file_id(file_name)

    def add_function(self, name):
        if name not in self._funcs:
            self._funcs.append(name)
            return len(self._funcs) - 1
        else:
            return self.resolve_function_id(name)

    def add_action(self, comment, callback=False):
        if comment not in self._actions:
            self._actions.append(comment)
            action_id = len(self._actions) - 1
            if callback:
                self._callback_actions.append(action_id)
        else:
            action_id = self.resolve_action_id(comment)

        return action_id

    def add_aux_func(self, identifier, is_callback, formal_arg_names):
        self.aux_funcs[identifier] = {'is callback': is_callback, 'formal arg names': formal_arg_names}

    def add_emg_comment(self, file, line, data):
        if file not in self.emg_comments:
            self.emg_comments[file] = dict()
        self.emg_comments[file][line] = data

    def resolve_file_id(self, file):
        return self._files.index(file)

    def resolve_file(self, identifier):
        return self._files[identifier]

    def resolve_function_id(self, name):
        return self._funcs.index(name)

    def add_invariant(self, invariant, node_id):
        self.invariants[node_id] = invariant

    def resolve_function(self, identifier):
        return self._funcs[identifier]

    def resolve_action_id(self, comment):
        return self._actions.index(comment)

    def process_comment(self, comment: str) -> str:
        if len(comment) > self.MAX_COMMENT_LENGTH:
            comment = comment[:self.MAX_COMMENT_LENGTH] + "..."
        return comment

    def add_model_function(self, func_name: str, comment: str = None):
        if not comment:
            comment = func_name
        func_id = self.add_function(func_name)
        self._model_funcs[func_id] = comment
        self._spec_funcs[func_name] = comment

    def process_verifier_notes(self):
        # Get information from sources.
        self.parse_model_comments()
        self._logger.info('Mark witness with model comments')
        if self._model_funcs or self._notes:
            self.is_notes = True

        warn_edges = list()
        for edge in self._edges:
            if 'warn' in edge:
                warn_edges.append(edge['warn'])
            file_id = edge.get('file', None)
            if isinstance(file_id, int):
                file = self.resolve_file(file_id)
            else:
                continue

            start_line = edge.get('start line')

            if 'enter' in edge:
                func_id = edge['enter']
                if func_id in self._model_funcs:
                    note = self._model_funcs[func_id]
                    self._logger.debug("Add note {!r} for model function '{}'".
                                       format(note,self.resolve_function(func_id)))
                    edge['note'] = self.process_comment(note)
                if func_id in self._env_models:
                    env_note = self._env_models[func_id]
                    self._logger.debug("Add note {!r} for environment function '{}'".
                                       format(env_note,self.resolve_function(func_id)))
                    edge['env'] = self.process_comment(env_note)

            if file_id in self._notes and start_line in self._notes[file_id]:
                note = self._notes[file_id][start_line]
                self._logger.debug("Add note {!r} for statement from '{}:{}'".format(note, file, start_line))
                edge['note'] = self.process_comment(note)
            elif file_id in self._asserts and start_line in self._asserts[file_id]:
                warn = self._asserts[file_id][start_line]
                self._logger.debug("Add warning {!r} for statement from '{}:{}'".format(warn, file, start_line))
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
                    last_edge['warn'] = "Violation of '{}'".format(self.process_comment(last_edge['note']))
                    del last_edge['note']
                else:
                    last_edge['warn'] = 'Property violation'
        del self._model_funcs, self._notes, self._asserts, self._env_models

    def parse_model_comments(self):
        self._logger.info('Parse model comments from source files referred by witness')
        emg_comment = re.compile('/\*\sLDV\s(.*)\s\*/')

        for file_id, file in self.files:
            if not os.path.isfile(file):
                continue

            self._logger.debug('Parse model comments from {!r}'.format(file))

            with open(file, encoding='utf8', errors='ignore') as fp:
                line = 0
                for text in fp:
                    line += 1

                    # Try match EMG comment
                    # Expect comment like /* TYPE Instance Text */
                    match = emg_comment.search(text)
                    if match:
                        data = json.loads(match.group(1))
                        self.add_emg_comment(file_id, line, data)

                    # Match rest comments
                    match = re.search(r'/\*\s+({0})\s+(\S+)\s+(.*)\*/'.format(self.MODEL_COMMENT_TYPES), text)
                    if match:
                        kind, func_name, comment = match.groups()

                        comment = comment.rstrip()
                        if kind in ("NOTE", "WARN"):
                            comment = "{} {}".format(func_name, comment)

                            if file_id not in self._notes:
                                self._notes[file_id] = dict()
                            self._notes[file_id][line + 1] = comment
                            self._logger.debug(
                                "Get note '{0}' for statement from '{1}:{2}'".format(comment, file, line + 1))
                            # Some assertions will become warnings.
                            if kind == 'ASSERT':
                                if file_id not in self._asserts:
                                    self._asserts[file_id] = dict()
                                self._asserts[file_id][line + 1] = comment
                                self._logger.debug("Get assertion '{0}' for statement from '{1}:{2}'".
                                                   format(comment, file, line + 1))
                        else:
                            func_name = func_name.rstrip()
                            if not comment:
                                comment = func_name

                            formal_arg_names = []
                            if kind in ('AUX_FUNC', 'AUX_FUNC_CALLBACK'):
                                # Get necessary function declaration located on following line.
                                try:
                                    func_decl = next(fp)
                                    # Don't forget to increase counter.
                                    line += 1

                                    # Try to get names for formal arguments (in form "type name") that is required for
                                    # removing auxiliary function calls.
                                    match = re.search(r'{0}\s*\((.+)\)'.format(func_name), func_decl)
                                    if match:
                                        formal_args_str = match.group(1)

                                        # Remove arguments of function pointers and braces around corresponding argument
                                        # names.
                                        formal_args_str = re.sub(r'\((.+)\)\(.+\)', '\g<1>', formal_args_str)

                                        for formal_arg in formal_args_str.split(','):
                                            match = re.search(r'^.*\W+(\w+)\s*$', formal_arg)

                                            # Give up if meet complicated formal argument.
                                            if not match:
                                                formal_arg_names = []
                                                break

                                            formal_arg_names.append(match.group(1))
                                except StopIteration:
                                    self._logger.warning('Auxiliary function definition does not exist')
                                    continue

                            # Deal with functions referenced by witness.
                            try:
                                func_id = self.resolve_function_id(func_name)
                            except ValueError:
                                self.add_function(func_name)
                                func_id = self.resolve_function_id(func_name)

                            if kind == 'AUX_FUNC':
                                self.add_aux_func(func_id, False, formal_arg_names)
                                self._logger.debug("Get auxiliary function '{0}' from '{1}:{2}'".
                                                   format(func_name, file, line))
                            elif kind == 'AUX_FUNC_CALLBACK':
                                self.add_aux_func(func_id, True, formal_arg_names)
                                self._logger.debug("Get auxiliary function '{0}' for callback from '{1}:{2}'".
                                                   format(func_name, file, line))
                            elif kind == 'ENVIRONMENT_MODEL':
                                self._env_models[func_id] = comment
                                self._logger.debug("Get environment model '{0}' for function '{1}' from '{2}:{3}'".
                                                   format(comment, func_name, file, line))
                            else:
                                self._model_funcs[func_id] = comment
                                self._logger.debug("Get note '{0}' for model function '{1}' from '{2}:{3}'".
                                                   format(comment, func_name, file, line))

    def add_thread(self, thread_id: str):
        self._threads.append(thread_id)

    def final_checks(self, entry_point="main"):
        # Check for warnings
        if self.witness_type == 'violation':
            if not self.is_call_stack:
                self._warnings.append(
                    'No call stack (please add tags "enterFunction" and "returnFrom" to improve visualization)')
            if not self.is_conditions:
                self._warnings.append('No conditions (please add tags "control" to improve visualization)')
            if not self.is_main_function and self._edges:
                self._warnings.append('No entry point (entry point call was generated)')
                entry_elem = {
                    'enter': self.add_function(entry_point),
                    'start line': 0,
                    'file': 0,
                    'env': 'entry point',
                    'source': "{}()".format(entry_point)
                }
                if not self._threads:
                    entry_elem['thread'] = '1'
                else:
                    entry_elem['thread'] = str(self._threads[0])
                self._edges.insert(0, entry_elem)
            '''
            if not self.is_notes:
                self._warnings.append(
                    'Optional: no violation hints (please add tags "note" and "warn" to improve visualization)')
            '''
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
        else:
            return None


def get_original_file(edge):
    return edge.get('original file', edge['file'])


def get_original_start_line(edge):
    return edge.get('original start line', edge['start line'])
