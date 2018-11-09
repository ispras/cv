import logging
import operator
import os
import re
from xml.dom import minidom

from config import COMPONENT_MEA

_CALL = 'CALL'
_RET = 'RET'

# Predefined set for SMG.
_PREDEFINED_FUNCTIONS = {
    "send_w_s": 1,
    "send": 1,
    "attach": 1,
    "free_buf": 1,
    "external_allocated_data": 1,
    "ext_allocation": 1,
    "receive": 1,
    "receive_w_tmo": 1,
    "get_pcb": 1,
    "get_env": 1,
    "receive_from": 1,
    "get_pid_list": 1,
    "malloc": 1,
    "__kmalloc": 1,
    "kmalloc": 1,
    "ldv_malloc": 1,
    "alloc": 1,
    "realloc": 1,
    "heap_alloc_private": 1,
    "kmalloc_array": 1,
    "kcalloc": 1,
    "calloc": 1,
    "kzalloc": 1,
    "kzalloc_node": 1,
    "ldv_zalloc": 1,
    "free": 1,
    "kfree": 1,
    "kfree_const": 1,
    "heap_free_private": 1
}


def check_error_trace(new_error_trace: str):
    """
    Checks new_error_trace
    :param new_error_trace:
    :return: True if trace is correct and False otherwise.
    """
    if not os.path.exists(new_error_trace):
        return False
    if os.stat(new_error_trace).st_size == 0:
        return False
    with open(new_error_trace, errors='ignore') as fp:
        try:
            dom = minidom.parse(fp)
            if not dom:
                return False
            graphml = dom.getElementsByTagName('graphml')[0]
            graph = graphml.getElementsByTagName('graph')[0]
            for edge in graph.getElementsByTagName('node'):
                for data in edge.getElementsByTagName('data'):
                    if data.getAttribute('key') == 'violation':
                        # Trace should be fully printed till property violation.
                        return True
        except:
            return False
    return False


class MEA(object):
    """
    Compare error traces by means of some filter.
    """
    def __init__(self, error_traces, traces_filter="no", debug=False):
        self.error_traces = error_traces
        self.filter = traces_filter
        self.__cached_traces = []
        self.__cache = {}
        if traces_filter == 'model_functions_smg':
            self.__cache = _PREDEFINED_FUNCTIONS
        self.assertion = None
        self.debug = debug
        logger_level = logging.DEBUG if self.debug else logging.INFO
        self.logger = logging.getLogger(name=COMPONENT_MEA)
        self.logger.setLevel(logger_level)

    def execute(self):
        result = []

        # Need to sort traces for deterministic results.
        # Moreover, first traces are usually more "simpler".
        sorted_traces = {}
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
        self.logger.debug("There are {} traces".format(len(sorted_traces)))

        for identifier, error_trace in sorted_traces:
            if os.stat(error_trace).st_size == 0:
                self.logger.debug("Trace '{}' is empty".format(error_trace))
            elif self.is_equal(error_trace):
                self.logger.debug("Trace '{}' is equal".format(error_trace))
            else:
                result.append(error_trace)
                self.logger.debug("Trace '{}' is new".format(error_trace))
        self.logger.info("Filtering has been completed: {0} -> {1}".format(len(self.error_traces), len(result)))
        return result

    def is_equal(self, new_error_trace) -> bool:
        """
        Basic function for error traces comparison. Takes
        :param new_error_trace: New error trace, which is compared with processed_error_traces.
        :return: True if new_error_trace is equal to one of the processed_error_traces and False otherwise.
        """
        filters = {
            'model_functions': self.__model_functions_filter,
            'model_functions_smg': self.__model_functions_filter,
            'call_tree': self.__call_tree_filter,
            'no': self.__do_not_filter
        }
        return filters[self.filter](new_error_trace)

    def __model_functions_filter(self, new_error_trace) -> bool:
        """
        Comparison function, which compares model functions call trees.
        """
        with open(new_error_trace, errors='ignore') as fp:
            try:
                dom = minidom.parse(fp)
                if not dom:
                    return True
            except:
                return True

        graphml = dom.getElementsByTagName('graphml')[0]
        graph = graphml.getElementsByTagName('graph')[0]

        self.__get_model_functions(graphml)

        call_tree = [{"entry_point": _CALL}]
        for edge in graph.getElementsByTagName('edge'):
            for data in edge.getElementsByTagName('data'):
                if data.getAttribute('key') == 'enterFunction':
                    function_call = data.firstChild.data
                    call_tree.append({function_call: _CALL})
                if data.getAttribute('key') == 'returnFrom':
                    function_return = data.firstChild.data
                    if function_return in self.__cache:
                        call_tree.append({function_return: _RET})
                    else:
                        # Check from the last call of that function.
                        is_save = False
                        sublist = []
                        for elem in reversed(call_tree):
                            sublist.append(elem)
                            func_name = list(elem.keys()).__getitem__(0)
                            for mf in self.__cache.keys():
                                if func_name.__contains__(mf):
                                    is_save = True
                            if elem == {function_return: _CALL}:
                                sublist.reverse()
                                break
                        if is_save:
                            call_tree.append({function_return: _RET})
                        else:
                            call_tree = call_tree[:-sublist.__len__()]
        if call_tree not in self.__cached_traces:
            self.__cached_traces.append(call_tree)
            return False
        return True

    def __call_tree_filter(self, new_error_trace) -> bool:
        """
        Comparison function, which compares model functions call trees.
        """
        with open(new_error_trace, errors='ignore') as fp:
            try:
                dom = minidom.parse(fp)
                if not dom:
                    return True
            except:
                return True

        graphml = dom.getElementsByTagName('graphml')[0]
        graph = graphml.getElementsByTagName('graph')[0]

        call_tree = [{"entry_point": _CALL}]
        for edge in graph.getElementsByTagName('edge'):
            for data in edge.getElementsByTagName('data'):
                if data.getAttribute('key') == 'enterFunction':
                    function_call = data.firstChild.data
                    call_tree.append({function_call: _CALL})
                if data.getAttribute('key') == 'returnFrom':
                    function_return = data.firstChild.data
                    call_tree.append({function_return: _RET})

        if call_tree not in self.__cached_traces:
            self.__cached_traces.append(call_tree)
            return False
        return True

    def __do_not_filter(self, new_error_trace) -> bool:
        return False

    def __get_model_functions(self, graphml):
        graph = graphml.getElementsByTagName('graph')[0]
        stack = list()
        for edge in graph.getElementsByTagName('edge'):
            for data in edge.getElementsByTagName('data'):
                if data.getAttribute('key') == 'enterFunction':
                    func = data.firstChild.data
                    stack.append(func)
                if data.getAttribute('key') == 'returnFrom':
                    # func = data.firstChild.data  # check the name of the function?
                    stack.pop()
                if data.getAttribute('key') == 'warning':
                    if len(stack) > 0:
                        self.__cache[stack[len(stack)-1]] = 1
                if data.getAttribute('key') == 'note':
                    if len(stack) > 0:
                        self.__cache[stack[len(stack)-1]] = 1
