#!/usr/bin/python3

import argparse
import operator
import re
import time
import os
from xml.etree.ElementTree import ElementTree

from component import Component
from config import COMPONENT_MEA
from config import TAG_DEBUG

_CALL = 'CALL'
_RET = 'RET'
_ASSUME_TRUE = 'ASSUME TRUE'
_ASSUME_FALSE = 'ASSUME FALSE'


PARSER_GRAHML = "grahml"
PARSERS = [PARSER_GRAHML]
DEFAULT_PARSER = PARSER_GRAHML

CONVERSION_FUNCTION_CALL_TREE = "call_tree"
CONVERSION_FUNCTION_MODEL_FUNCTIONS = "model_functions"
CONVERSION_FUNCTION_CONDITIONS = "conditions"
CONVERSION_FUNCTIONS = [
    CONVERSION_FUNCTION_CALL_TREE,
    CONVERSION_FUNCTION_MODEL_FUNCTIONS,
    CONVERSION_FUNCTION_CONDITIONS
]
DEFAULT_CONVERSION_FUNCTION = CONVERSION_FUNCTION_MODEL_FUNCTIONS

COMPARISON_FUNCTION_NO = "no"
COMPARISON_FUNCTION_EQ = "eq"
COMPARISON_FUNCTION_IN = "in"
COMPARISON_FUNCTIONS = [
    COMPARISON_FUNCTION_NO,
    COMPARISON_FUNCTION_EQ,
    COMPARISON_FUNCTION_IN
]
DEFAULT_COMPARISON_FUNCTION = COMPARISON_FUNCTION_EQ

TAG_PARSER = "parser"
TAG_CONVERSION_FUNCTION = "conversion function"
TAG_COMPARISON_FUNCTION = "comparison function"


class MEA(Component):
    """
    Multiple Error Analysis (MEA) is aimed at processing several error traces, which violates the same property.
    Error traces are called equivalent, if they correspond to the same error.
    Error trace equivalence for two traces et1 and et2 is determined in the following way:
    et1 = et2 <=> comparison(conversion(parser(et1)), comparison(parser(et2))),
    where parser function parses the given file with error trace and returns its internal representation,
    conversion function transforms its internal representation (for example, by removing some elements) and
    comparison function compares its internal representation.
    """
    def __init__(self, general_config: dict, error_traces: list, rule: str, mea_config_file=None):
        super(MEA, self).__init__(COMPONENT_MEA, general_config)

        # List of files with error traces.
        self.error_traces = error_traces

        # Config options.
        self.parser = self.__get_option_for_rule(TAG_PARSER, DEFAULT_PARSER, rule)
        self.conversion_function = \
            self.__get_option_for_rule(TAG_CONVERSION_FUNCTION, DEFAULT_CONVERSION_FUNCTION, rule)
        self.comparison_function = \
            self.__get_option_for_rule(TAG_COMPARISON_FUNCTION, DEFAULT_COMPARISON_FUNCTION, rule)

        self.additional_model_functions = set()
        if mea_config_file and os.path.exists(mea_config_file):
            with open(mea_config_file, encoding='utf8', errors='ignore') as fd:
                for line in fd.readlines():
                    self.additional_model_functions.add(line.strip())

        # Cache of internal representation (i.e. result of comparison(parser(et))) of filtered traces.
        self.__internal_traces = list()

        # CPU time of each operation.
        self.parse_traces_time = 0.0
        self.conversion_function_time = 0.0
        self.comparison_function_time = 0.0

    def __get_option_for_rule(self, tag: str, default_value: str, rule: str):
        default = self.component_config.get(tag, default_value)
        return self.component_config.get(rule, {}).get(tag, default)

    def check_error_trace(self, error_trace: str) -> bool:
        """
        Check if error trace is correct.
        """
        root = self.parse(error_trace)
        if not root:
            return False
        prefix = root.tag[:-len("graphml")]
        if root.findall('./{0}graph/{0}node/{0}data[@key=\'violation\']'.format(prefix)):
            return True
        return False

    def check_error_traces(self) -> bool:
        """
        Check if there is at least one correct error trace.
        """
        for error_trace in self.error_traces:
            if self.check_error_trace(error_trace):
                return True
        return False

    def filter(self) -> list:
        """
        Filter error trace with specified configuration and return filtered traces.
        """

        if self.comparison_function == COMPARISON_FUNCTION_NO:
            self.logger.debug("Skipping filtering of error traces")
            return self.error_traces

        filtered_traces = []

        # Need to sort traces for deterministic results.
        # Moreover, first traces are usually more "simpler".
        sorted_traces = {}
        self.logger.debug("Sorting {} error traces".format(len(self.error_traces)))
        for trace in self.error_traces:
            identifier = re.search(r'witness\.(.*)\.graphml', trace).group(1)
            key = identifier
            if identifier.isdigit():
                try:
                    key = int(identifier)
                except:
                    pass
            sorted_traces[key] = trace
        sorted_traces = sorted(sorted_traces.items(), key=operator.itemgetter(0))

        self.logger.debug("Filtering error traces")
        for identifier, error_trace_file_name in sorted_traces:
            internal_trace = self.parse(error_trace_file_name)
            if not internal_trace:
                continue
            converted_trace = self.converse(internal_trace)
            self.logger.debug("Converted error trace {} into {}".format(error_trace_file_name, converted_trace))
            if not self.compare(converted_trace, error_trace_file_name):
                filtered_traces.append(error_trace_file_name)

        self.logger.info("Filtering has been completed: {0} -> {1}".format(len(self.error_traces),
                                                                           len(filtered_traces)))
        self.logger.debug("Parsing of error traces took {}s".format(round(self.parse_traces_time, 2)))
        self.logger.debug("Applying conversion function took {}s".format(round(self.conversion_function_time, 2)))
        self.logger.debug("Applying comparison function took {}s".format(round(self.comparison_function_time, 2)))
        return filtered_traces

    def parse(self, xml_file: str):
        """
        Parses error trace file and returns its internal representation.
        :param xml_file: file with error trace.
        :return: parsed xml or None in case of errors.
        """
        functions = {
            PARSER_GRAHML: self.__parser_graphml
        }
        start_time = time.process_time()
        result = functions[self.parser](xml_file)
        self.parse_traces_time += (time.process_time() - start_time)
        return result

    def __parser_graphml(self, xml_file: str):
        """
        Basic xml parser for graphml.
        """
        try:
            tree = ElementTree()
            tree.parse(xml_file)
            return tree.getroot()
        except Exception:
            # There are a lot of empty traces for MEA, so this should be a debug print.
            self.logger.debug("Parsing error trace {} has failed due to: ".format(xml_file), exc_info=True)
            return None

    def converse(self, internal_trace: ElementTree) -> list:
        """
        Converse parsed xml representation of error trace into list of elements.
        """
        functions = {
            CONVERSION_FUNCTION_MODEL_FUNCTIONS: self.__converse_model_functions,
            CONVERSION_FUNCTION_CALL_TREE: self.__converse_call_tree_filter,
            CONVERSION_FUNCTION_CONDITIONS: self.__converse_conditions
        }
        start_time = time.process_time()
        result = functions[self.conversion_function](internal_trace)
        self.conversion_function_time += (time.process_time() - start_time)
        return result

    def __converse_call_tree_filter(self, internal_trace) -> list:
        """
        Extract function call tree from error trace.
        """
        prefix = internal_trace.tag[:-len("graphml")]
        call_tree = [{"entry_point": _CALL}]
        for data in internal_trace.findall('./{0}graph/{0}edge/{0}data'.format(prefix)):
            key = data.attrib['key']
            if key == 'enterFunction':
                function_call = data.text
                call_tree.append({function_call: _CALL})
            elif key == 'returnFrom':
                function_return = data.text
                call_tree.append({function_return: _RET})
        return call_tree

    def __converse_conditions(self, internal_trace) -> list:
        """
        Extract list of all conditions from error trace.
        """
        prefix = internal_trace.tag[:-len("graphml")]
        assumes = []
        for edge in internal_trace.findall('./{0}graph/{0}edge'.format(prefix)):
            assume_type = None
            source_code = None
            for data in edge.findall('./{0}data'.format(prefix)):
                key = data.attrib['key']
                if key == 'control':
                    if data.text == "condition-true":
                        assume_type = _ASSUME_TRUE
                    elif data.text == "condition-false":
                        assume_type = _ASSUME_FALSE
                elif key == 'sourcecode':
                    source_code = data.text
            if assume_type:
                assumes.append({source_code: assume_type})
        return assumes

    def __converse_model_functions(self, internal_trace) -> list:
        """
        Convert error trace into model functions call tree.
        """
        prefix = internal_trace.tag[:-len("graphml")]

        model_functions = self.additional_model_functions.union(self.__get_model_functions(internal_trace, prefix))

        call_tree = [{"entry_point": _CALL}]
        for data in internal_trace.findall('./{0}graph/{0}edge/{0}data'.format(prefix)):
            key = data.attrib['key']
            if key == 'enterFunction':
                function_call = data.text
                call_tree.append({function_call: _CALL})
            elif key == 'returnFrom':
                function_return = data.text
                if function_return in model_functions:
                    call_tree.append({function_return: _RET})
                else:
                    # Check from the last call of that function.
                    is_save = False
                    sublist = []
                    for elem in reversed(call_tree):
                        sublist.append(elem)
                        func_name = list(elem.keys()).__getitem__(0)
                        for mf in model_functions:
                            if func_name.__contains__(mf):
                                is_save = True
                        if elem == {function_return: _CALL}:
                            sublist.reverse()
                            break
                    if is_save:
                        call_tree.append({function_return: _RET})
                    else:
                        call_tree = call_tree[:-sublist.__len__()]
        return call_tree

    def __get_model_functions(self, internal_trace, prefix: str) -> set:
        """
        Extract model functions from error trace.
        """
        stack = list()
        model_functions = set()
        for data in internal_trace.findall('./{0}graph/{0}edge/{0}data'.format(prefix)):
            key = data.attrib['key']
            if key == 'enterFunction':
                func = data.text
                stack.append(func)
            elif key == 'returnFrom':
                # func = data.text  # check the name of the function?
                stack.pop()
            elif key == 'warning':
                if len(stack) > 0:
                    model_functions.add(stack[len(stack) - 1])
            elif key == 'note':
                if len(stack) > 0:
                    model_functions.add(stack[len(stack) - 1])
        return model_functions

    def compare(self, converted_trace: list, file_name: str) -> bool:
        """
        Compare internal representation of error traces.
        """
        functions = {
            COMPARISON_FUNCTION_EQ: self.__compare_eq,
            COMPARISON_FUNCTION_IN: self.__compare_in
        }
        start_time = time.process_time()
        equivalent_trace = functions[self.comparison_function](converted_trace)
        if equivalent_trace:
            self.logger.debug("Error trace {} is equivalent to already filtered error trace {}".
                              format(file_name, equivalent_trace))
            equivalent = True
        else:
            self.__internal_traces.append((converted_trace, file_name))
            equivalent = False
        self.comparison_function_time += (time.process_time() - start_time)
        return equivalent

    def __compare_eq(self, new_converted_trace: list) -> str:
        """
        Error traces are equivalent if their internal representation is equal.
        """
        for filtered_converted_trace, filtered_file_name in self.__internal_traces:
            if filtered_converted_trace == new_converted_trace:
                return filtered_file_name
        return ""

    def __compare_in(self, new_converted_trace: list) -> str:

        """
        Error traces are equivalent if new trace is included in the old trace.
        """
        # TODO: not implemented.
        raise NotImplementedError


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--conversion", help="conversion function", required=False, default=DEFAULT_CONVERSION_FUNCTION)
    parser.add_argument("--comparison", help="comparison function", required=False, default=DEFAULT_COMPARISON_FUNCTION)
    parser.add_argument("--parser", help="parser", required=False, default=DEFAULT_PARSER)
    parser.add_argument("--model-functions-file", dest='mf', help="file with additional model functions",
                        required=False)
    parser.add_argument("--directory", help="directory with error traces", required=True)
    parser.add_argument('--debug', '-d', action='store_true')

    options = parser.parse_args()

    config = {
        COMPONENT_MEA: {
            TAG_COMPARISON_FUNCTION: options.comparison,
            TAG_CONVERSION_FUNCTION: options.conversion,
            TAG_PARSER: options.parser,
            TAG_DEBUG: options.debug
        }
    }

    import glob
    traces = glob.glob(os.path.join(options.directory, "witness*"))
    mea = MEA(config, traces, "", options.mf)
    traces = mea.filter()
    mea.logger.info("Filtered traces:")
    for filtered_trace in traces:
        mea.logger.info(filtered_trace)
