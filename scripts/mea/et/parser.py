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
# pylint: disable=line-too-long
"""
Parser for witnesses.
"""

import os
import re
from xml.etree import ElementTree

from mea.et.internal_witness import InternalWitness, WITNESS_TYPE_VIOLATION, WITNESS_TYPE_CORRECTNESS


class WitnessParser:
    """
    Class parses a given witness (both correctness and violation are supported).
    """
    WITNESS_NS = {'graphml': 'http://graphml.graphdrawing.org/xmlns'}

    def __init__(self, logger, witness, source_dir=None):
        self._logger = logger
        self.entry_point = None
        # TODO: specify this option
        self._is_read_line_directives = False
        self.src_files_map = {}
        self.source_dir = source_dir
        self._violation_hints = set()
        self.default_program_file = None  # default source file
        self.global_program_file = None  # ~CIL file
        self.internal_witness = InternalWitness(logger)
        self._parse_witness(witness)
        self._check_given_files()

    def __check_for_default_file(self, name: str, edge: dict):
        try:
            identifier = self.internal_witness.add_file(self.__resolve_src_path(name))
            last_used_file = identifier
            edge['file'] = last_used_file
            return last_used_file
        except FileNotFoundError:
            # File is missing, warning already was generated, parser should continue its work.
            return None

    def _check_given_files(self):
        last_used_file = None
        for edge in self.internal_witness.get_edges():
            if 'file' in edge and edge['file'] is not None:
                last_used_file = edge['file']
            elif self.default_program_file:
                tmp_file = self.__check_for_default_file(self.default_program_file, edge)
                if tmp_file:
                    last_used_file = tmp_file
            elif last_used_file is not None:
                edge['file'] = last_used_file
            elif self.global_program_file:
                tmp_file = self.__check_for_default_file(self.global_program_file, edge)
                if tmp_file:
                    last_used_file = tmp_file
            else:
                self._logger.warning(f"There is no source file for edge {edge}")

    def __check_file_name(self, name: str):
        name = self.__resolve_src_path(name)
        if os.path.exists(name):
            return name
        return None

    def __resolve_src_path(self, name: str):
        """
        This function implements very specific logic.
        """
        if os.path.exists(name):
            return name
        if self.source_dir:
            abs_path = os.path.join(self.source_dir, name)
            if os.path.exists(abs_path):
                return abs_path
        # TODO: workaround for some tools.
        resolved_name = re.sub(r'.+/vcloud-\S+/worker/working_dir_[^/]+/', '', name)
        if os.path.exists(resolved_name):
            return resolved_name
        return name

    def _parse_witness(self, witness):
        self._logger.info(f'Parse witness {witness}')
        if os.stat(witness).st_size == 0:
            raise ElementTree.ParseError("Witness is empty")
        with open(witness, encoding='utf8') as witness_obj:
            tree = ElementTree.parse(witness_obj)
        root = tree.getroot()
        graph = root.find('graphml:graph', self.WITNESS_NS)
        for data in root.findall('graphml:key', self.WITNESS_NS):
            name = data.attrib.get('attr.name')
            if name in ("originFileName", "originfile"):
                for def_data in data.findall('graphml:default', self.WITNESS_NS):
                    new_name = self.__check_file_name(def_data.text)
                    if new_name:
                        self.default_program_file = new_name
                        break
        if not graph:
            return
        for data in graph.findall('graphml:data', self.WITNESS_NS):
            key = data.attrib.get('key')
            if key == 'programfile':
                new_name = self.__check_file_name(data.text)
                if new_name:
                    self.global_program_file = new_name
                    if not self._is_read_line_directives:
                        if not self.src_files_map:
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
                                            file_name = m.group(2)[1:-1]
                                            # Do not treat artificial file references
                                            if not os.path.basename(file_name) == '<built-in>':
                                                orig_file_id = self.internal_witness.add_file(file_name)
                                    else:
                                        if orig_file_id and orig_file_line_num:
                                            self.src_files_map[line_num] = (orig_file_id, orig_file_line_num)
                                        orig_file_line_num += 1
                                    line_num += 1
            elif key == 'witness-type':
                witness_type = data.text
                if witness_type == 'correctness_witness':
                    self.internal_witness.witness_type = WITNESS_TYPE_CORRECTNESS
                elif witness_type == 'violation_witness':
                    self.internal_witness.witness_type = WITNESS_TYPE_VIOLATION
                else:
                    self._logger.warning(f"Unsupported witness type: {witness_type}")
            elif key == 'specification':
                automaton = data.text
                for line in automaton.split('\n'):
                    note = None
                    match = re.search(r'init\((\w+)\(\)\)', line)
                    if match:
                        self.entry_point = match.group(1)
                    match = re.search(r'ERROR\(\"(.+)"\)', line)
                    if match:
                        note = match.group(1)
                    match = re.search(r'MATCH\s*{\S+\s*=(\S+)\(.*\)}', line)
                    if match:
                        func_name = match.group(1)
                        self.internal_witness.add_model_function(func_name, note)
                        self._violation_hints.add(func_name)
                        continue
                    match = re.search(r'MATCH\s*{(\S+)\(.*\)}', line)
                    if match:
                        func_name = match.group(1)
                        self._violation_hints.add(func_name)
                        self.internal_witness.add_model_function(func_name, note)
                        continue
        self.__parse_witness_data(graph)
        sink_nodes_map = self.__parse_witness_nodes(graph)
        self.__parse_witness_edges(graph, sink_nodes_map)

    def __parse_witness_data(self, graph):
        for data in graph.findall('graphml:data', self.WITNESS_NS):
            if 'klever-attrs' in data.attrib and data.attrib['klever-attrs'] == 'true':
                self.internal_witness.add_attr(
                    data.attrib.get('key'), data.text,
                    data.attrib.get('associate', "false") == 'true',
                    data.attrib.get('compare', "false") == 'true')

    def __parse_witness_nodes(self, graph):
        sink_nodes_map = {}
        unsupported_node_data_keys = {}
        nodes_number = 0

        for node in graph.findall('graphml:node', self.WITNESS_NS):
            is_sink = False

            node_id = node.attrib['id']
            for data in node.findall('graphml:data', self.WITNESS_NS):
                data_key = data.attrib.get('key')
                if data_key == 'entry':
                    self.internal_witness.add_entry_node_id(node_id)
                    self._logger.debug(f'Parse entry node {node_id}')
                elif data_key == 'sink':
                    is_sink = True
                    self._logger.debug(f'Parse sink node {node_id}')
                elif data_key == 'violation':
                    pass
                elif data_key == 'invariant':
                    self.internal_witness.add_invariant(data.text, node_id)
                elif data_key not in unsupported_node_data_keys:
                    self._logger.warning(f'Node data key {data_key} is not supported')
                    unsupported_node_data_keys[data_key] = None

            # Do not track sink nodes as all other nodes.
            # All edges leading to sink nodes will be excluded as well.
            if is_sink:
                sink_nodes_map[node_id] = None
            else:
                nodes_number += 1

        self._logger.debug(
            f'Parse {nodes_number} nodes and {len(sink_nodes_map)} sink nodes')
        return sink_nodes_map

    def __parse_witness_edges(self, graph, sink_nodes_map):
        unsupported_edge_data_keys = {}
        # Use maps for source files and functions as for nodes. Add artificial map to 0 for
        # default file without explicitly specifying its path.
        # The number of edges leading to sink nodes. Such edges will be completely removed.
        sink_edges_num = 0
        edges_num = 0
        is_source_file = False
        is_entry_point = False

        for edge in graph.findall('graphml:edge', self.WITNESS_NS):

            target_node_id = edge.attrib.get('target')

            if target_node_id in sink_nodes_map:
                sink_edges_num += 1
                continue

            # Update lists of input and output edges for source and target nodes.
            _edge = self.internal_witness.add_edge(target_node_id)

            start_offset = 0
            end_offset = 0
            condition = None
            invariant = None
            invariant_scope = None
            cur_notes = {}
            for data in edge.findall('graphml:data', self.WITNESS_NS):
                data_key = data.attrib.get('key')
                if data_key == 'originfile':
                    try:
                        identifier = self.internal_witness.add_file(
                            self.__resolve_src_path(data.text))
                        _edge['file'] = identifier
                    except FileNotFoundError:
                        _edge['file'] = None
                elif data_key == 'startline':
                    _edge['start line'] = int(data.text)
                elif data_key == 'endline':
                    _edge['end line'] = int(data.text)
                elif data_key == 'sourcecode':
                    is_source_file = True
                    _edge['source'] = data.text
                elif data_key in ('enterFunction', 'returnFrom', 'assumption.scope'):
                    function_name = data.text
                    func_index = self.internal_witness.add_function(function_name)
                    if data_key == 'enterFunction':
                        # Automaton format
                        if func_index - len(self._violation_hints) == 0:
                            if self.entry_point:
                                if self.entry_point == function_name:
                                    self.internal_witness.is_main_function = True
                                    if self.internal_witness.witness_type == WITNESS_TYPE_VIOLATION:
                                        _edge['entry_point'] = "entry point"
                                        is_entry_point = True
                            else:
                                self.internal_witness.is_main_function = True
                        else:
                            self.internal_witness.is_call_stack = True
                        func_id = self.internal_witness.resolve_function_id(function_name)
                        _edge['enter'] = func_id
                        if not is_entry_point and \
                                self.internal_witness.witness_type == WITNESS_TYPE_VIOLATION:
                            _edge['entry_point'] = "entry point"
                            self.internal_witness.add_thread("decl")
                            is_entry_point = True
                    elif data_key == 'returnFrom':
                        _edge['return'] = self.internal_witness.resolve_function_id(function_name)
                    else:
                        _edge['assumption scope'] = self.internal_witness.resolve_function_id(
                            function_name)
                elif data_key == 'control':
                    val = data.text
                    condition = val
                    if val == 'condition-true':
                        _edge['condition'] = True
                    elif val == 'condition-false':
                        _edge['condition'] = False
                    self.internal_witness.is_conditions = True
                elif data_key == 'assumption':
                    _edge['assumption'] = data.text
                elif data_key == 'threadId':
                    if not is_entry_point:
                        _edge['thread'] = "decl"
                    else:
                        _edge['thread'] = data.text
                    self.internal_witness.add_thread(data.text)
                elif data_key == 'startoffset':
                    start_offset = int(data.text)
                elif data_key == 'endoffset':
                    end_offset = int(data.text)
                elif data_key in ('note', 'warning'):
                    tag, note_desc = self.internal_witness.process_note(data_key, data.text)
                    cur_notes[tag] = note_desc
                elif data_key == 'env':
                    _edge['env'] = self.internal_witness.process_comment(data.text)
                elif data_key not in unsupported_edge_data_keys:
                    self._logger.warning(f'Edge data key {data_key} is not supported')
                    unsupported_edge_data_keys[data_key] = None

            for tag, note_desc in cur_notes.items():
                # Actually there is only one note available.
                self._logger.debug(f"Add verifier {tag}: '{note_desc}' for edge {_edge}")
                new_edge = self.internal_witness.add_edge(target_node_id, _edge)
                new_edge[tag] = note_desc
                self.internal_witness.is_notes = True

            if invariant and invariant_scope:
                self.internal_witness.add_invariant(invariant, invariant_scope)

            if "source" not in _edge:
                _edge['source'] = ""
                if 'enter' in _edge:
                    _edge['source'] = self.internal_witness.get_func_name(_edge['enter'])
                elif 'return' in _edge:
                    _edge['source'] = 'return'
                elif not is_source_file:
                    if 'assumption' in _edge:
                        _edge['source'] = _edge['assumption']
                    elif 'start line' in _edge:
                        if start_offset and self.global_program_file:
                            src_file = self.global_program_file
                        elif 'file' in _edge:
                            src_file = self.internal_witness.get_file_name(_edge['file'])
                            if not src_file and self.global_program_file:
                                src_file = self.global_program_file
                        elif self.global_program_file:
                            src_file = self.global_program_file
                        else:
                            src_file = None
                        if src_file:
                            with open(src_file, encoding='utf8') as src_obj:
                                if start_offset:
                                    offset = 1
                                    if end_offset:
                                        offset += end_offset - start_offset
                                    src_obj.seek(start_offset)
                                    _edge['source'] = src_obj.read(offset)
                                else:
                                    counter = 1
                                    for line in src_obj.readlines():
                                        if counter == _edge['start line']:
                                            line = line.rstrip().lstrip()
                                            if 'condition' in _edge:
                                                res = re.match(r'[^(]*\((.+)\)[^)]*', line)
                                                if res:
                                                    line = res.group(1)
                                            _edge['source'] = line
                                            break
                                        counter += 1
                                if condition == 'condition-false':
                                    _edge['source'] = f"!({_edge['source']})"

            if 'thread' not in _edge:
                _edge['thread'] = "0"
            if 'start line' not in _edge:
                _edge['start line'] = 0

            edges_num += 1

        if not self._is_read_line_directives:
            for edge in self.internal_witness.get_edges():
                if 'start line' in edge:
                    try:
                        start_line = edge['start line']
                        src_file_id, src_file_line = self.src_files_map[start_line]
                        edge['start line'] = src_file_line
                        edge['file'] = src_file_id
                    except KeyError:
                        pass

        self._logger.debug(f'Parse {edges_num} edges and {sink_edges_num} sink edges')
