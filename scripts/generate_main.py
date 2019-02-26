#!/usr/bin/python3

import json
import os
import re

from component import Component
from config import *

DEFAULT_TYPE = "int"
DEFAULT_VOID = "void"
DEFAULT_THREAD_CREATE_FUNCTION = "ldv_thread_create"
DEFAULT_CHECK_FINAL_STATE_FUNCTION = "ldv_check_final_state"
ARGUMENT_PREFIX = "ldv_"

# Entry-points file tags.
TAG_ENTRYPOINTS = "entrypoints"
TAG_INCLUDE = "include"
TAG_RETURN = "return"
TAG_ARGS = "args"
TAG_STATIC_PROTOTYPE = "static prototype"

# Config tags.
TAG_STRATEGIES = "strategies"
TAG_PRINT_PROTOTYPES = "print prototypes"
TAG_IGNORE_TYPES = "ignore types"

# Strategies.
PARTIAL_STRATEGY = "partial"
COMBINED_STRATEGY = "combined"
THREADED_STRATEGY = "threaded"
SIMPLIFIED_THREADED_STRATEGY = "simplified_threaded"
THREADED_STRATEGY_NONDET = "threaded_nondet"
THREADED_COMBINED_STRATEGY = "threaded_combined"
MAIN_GENERATOR_STRATEGIES = [PARTIAL_STRATEGY, COMBINED_STRATEGY, THREADED_STRATEGY, THREADED_STRATEGY_NONDET,
                             THREADED_COMBINED_STRATEGY, SIMPLIFIED_THREADED_STRATEGY]


def get_formatted_type(origin):
    formatted_type = re.sub(r' ', "_", origin)
    formatted_type = re.sub(r'\*', "", formatted_type)
    return ARGUMENT_PREFIX + formatted_type


def simplify_type(var_type: str):
    res = re.sub(r'\s', '_', var_type)
    return re.sub(r'\*', '_pointer_', res)


class MainGenerator(Component):
    """
    This component is used for generating file with main function, which calls specified entry points.
    """

    def __init__(self, config: dict, input_file: str):
        super(MainGenerator, self).__init__(COMPONENT_MAIN_GENERATOR, config)

        # Config.
        self.ignore_types = self.component_config.get(TAG_IGNORE_TYPES, False)
        self.print_prototypes = self.component_config.get(TAG_PRINT_PROTOTYPES, True)
        self.specified_strategies = self.component_config.get(TAG_STRATEGIES, {})
        for rule, strategy in self.specified_strategies.items():
            if strategy not in MAIN_GENERATOR_STRATEGIES:
                self.logger.warning("Specified strategy '{}' does not exist. Using default strategy".format(strategy))
                self.specified_strategies[rule] = None

        # Entry-points file parsing.
        with open(input_file, errors='ignore') as data_file:
            data = json.load(data_file)

        self.entrypoints = data.get(TAG_ENTRYPOINTS)
        self.metadata = data.get(TAG_METADATA, {})

        self.callers = list()
        statics = set()
        for caller, params in sorted(self.entrypoints.items()):
            if TAG_STATIC_PROTOTYPE in params:
                statics.add(caller)
                caller += STATIC_SUFFIX
                self.entrypoints[caller] = params
            self.callers.append(caller + ENTRY_POINT_SUFFIX)

        for static in statics:
            del self.entrypoints[static]

    def get_strategy(self, rule: str) -> str:
        specified_strategy = self.specified_strategies.get(rule, None)
        if specified_strategy:
            return specified_strategy
        if rule == RULE_COVERAGE:
            strategy = COMBINED_STRATEGY
        elif rule == RULE_COV_AUX_OTHER:
            strategy = PARTIAL_STRATEGY
        elif rule == RULE_MEMSAFETY:
            strategy = PARTIAL_STRATEGY
        elif rule == RULE_RACES:
            strategy = THREADED_STRATEGY
        elif rule == RULE_DEADLOCK:
            strategy = THREADED_STRATEGY
        elif rule == RULE_TERMINATION:
            strategy = PARTIAL_STRATEGY
        elif rule == RULE_COV_AUX_RACES:
            strategy = THREADED_COMBINED_STRATEGY
        else:
            strategy = PARTIAL_STRATEGY
        return strategy

    def __get_source_directories(self) -> set:
        source_dirs = set()
        for sources in self.config.get(COMPONENT_BUILDER, {}).get(TAG_SOURCES, []):
            if TAG_SOURCE_DIR in sources:
                source_dirs.add(sources.get(TAG_SOURCE_DIR))
        return source_dirs

    def add_static_prototypes(self) -> None:
        for caller, params in self.entrypoints.items():
            if TAG_STATIC_PROTOTYPE in params:
                args = []
                args_with_types = []
                counter = 0
                for arg in params.get(TAG_ARGS, []):
                    args.append("arg_{}".format(counter))
                    args_with_types.append("{} arg_{}".format(arg, counter))
                    counter += 1
                if not args_with_types:
                    args_with_types.append(DEFAULT_VOID)
                static_declaration = "\nvoid {}({})\n{{\n  {}({});\n}}\n".format(caller, ", ".join(args_with_types),
                                                                                 caller[:-len(STATIC_SUFFIX)],
                                                                                 ", ".join(args))
                for source_dir in self.__get_source_directories():
                    name = os.path.join(source_dir, params.get(TAG_STATIC_PROTOTYPE))
                    if os.path.exists(name):
                        if self.command_caller("echo '{}' >> {}".format(static_declaration, name)):
                            self.logger.warning("Can not append lines '{}' to file: {}".
                                                format(static_declaration, name))

    def generate_main(self, strategy: str, output_file: str) -> list:
        """
        This function generates environment model.
        :param strategy: defines strategy for environment model generation.
        :param output_file: model will be generated in this file.
        :return: list of all generated entrypoints, for which verifier should be launched.
        """
        callers = self.callers
        self.logger.info("Generating main file {} using strategy {}".format(output_file, strategy))

        with open(output_file, 'w', encoding='utf8') as fp:
            # Add header files.
            if not self.ignore_types:
                for header in self.metadata.get(TAG_INCLUDE, []):
                    fp.write("#include \"{}\"\n".format(header))
            if strategy in [THREADED_STRATEGY, THREADED_STRATEGY_NONDET, SIMPLIFIED_THREADED_STRATEGY]:
                fp.write("typedef unsigned long int pthread_t;\n"
                         "union pthread_attr_t {\n"
                         "  char __size[56];\n"
                         "  long int __align;\n"
                         "};\ntypedef union pthread_attr_t pthread_attr_t;\n\n"
                         "int ldv_thread_create(pthread_t *thread, pthread_attr_t const *attr,"
                         "                      void *(*start_routine)(void *), void *arg);\n\n"
                         "int ldv_thread_join(pthread_t thread, void **retval);\n\n"
                         "int ldv_thread_create_N(pthread_t **thread, pthread_attr_t const *attr,"
                         "                        void *(*start_routine)(void *), void *arg);\n\n"
                         "int ldv_thread_join_N(pthread_t **thread, void (*start_routine)(void *));\n\n")
            fp.write("\n/*This is generated main function*/\n\n"
                     "void {}(void);\n\n".format(DEFAULT_CHECK_FINAL_STATE_FUNCTION))

            # Parsing function definition.
            # Do not print in file, we do not know: are the arguments local or not

            nondet_funcs = set()
            for caller, params in self.entrypoints.items():
                ret_type = params.get(TAG_RETURN, DEFAULT_VOID)
                arguments = params.get(TAG_ARGS, [])
                arg_names = []
                arg_defs = []
                arg_types = []
                local_var_defs = []
                i = 0
                for arg in arguments:
                    if self.ignore_types:
                        var_type = DEFAULT_TYPE
                    else:
                        var_type = arg.get('type', DEFAULT_TYPE)
                    if re.search(r'\$', var_type):
                        # Complicated type like function pointer - just replace $ to a caller
                        var_name = "complicated_type_" + caller + "_" + str(i)
                        # Do not format type and use it as it is
                        var_def = re.sub(r'\$', var_name, var_type)
                    else:
                        var_name = get_formatted_type(var_type) + "_" + caller + "_" + str(i)
                        if re.search(r' \*', var_type):
                            # Already has valuable space
                            var_def = var_type + var_name
                        else:
                            var_def = var_type + " " + var_name

                    global_scope = arg.get('global scope', True)
                    if global_scope:
                        fp.write(var_def + ";\n")
                        if var_type not in nondet_funcs:
                            nondet_funcs.add(var_type)
                            fp.write("extern {} __VERIFIER_nondet_{}();\n".format(var_type, simplify_type(var_type)))
                        var_def = var_name + " = ({})__VERIFIER_nondet_{}();\n".format(var_type,
                                                                                       simplify_type(var_type))
                        local_var_defs.append(var_def)
                    else:
                        local_var_defs.append(var_def + ";\n")
                    arg_names.append(var_name)
                    arg_defs.append(var_def)
                    arg_types.append(var_type)
                    i += 1

                if self.print_prototypes:
                    if arg_types:
                        arg_def_str = ", ".join(arg_types)
                    else:
                        arg_def_str = DEFAULT_VOID
                    fp.write("extern {0} {1}({2});\n".format(ret_type, caller, arg_def_str))

                if strategy in [THREADED_STRATEGY, THREADED_STRATEGY_NONDET]:
                    caller_args = DEFAULT_VOID + "* arg"
                    ret_caller_type = DEFAULT_VOID + "*"
                else:
                    caller_args = DEFAULT_VOID
                    ret_caller_type = DEFAULT_VOID
                fp.write("{0} {1}{2}({3}) {{\n".format(ret_caller_type, caller, ENTRY_POINT_SUFFIX, caller_args))

                for local_var in local_var_defs:
                    fp.write("  {0}".format(local_var))

                fp.write("  {0}({1});\n".format(caller, ", ".join(arg_names)))
                if strategy == PARTIAL_STRATEGY:
                    fp.write("  {}();\n".format(DEFAULT_CHECK_FINAL_STATE_FUNCTION))
                fp.write("}\n\n")

            fp.write("extern int __VERIFIER_nondet_int();\n")

            if strategy in [SIMPLIFIED_THREADED_STRATEGY]:
                fp.write("void* {0}(void *) {{\n"
                         "  int nondet;\n".format(DEFAULT_MAIN + ENTRY_POINT_SUFFIX))
            elif strategy not in [PARTIAL_STRATEGY]:
                fp.write("void {0}(int argc, char *argv[]) {{\n"
                         "  int nondet;\n".format(DEFAULT_MAIN))

            if strategy in [COMBINED_STRATEGY, THREADED_COMBINED_STRATEGY]:
                fp.write("  while (1) {{\n".format(DEFAULT_MAIN))
                for caller, params in sorted(self.entrypoints.items()):
                    if strategy == THREADED_COMBINED_STRATEGY and not params.get("races", False):
                        continue
                    fp.write("    nondet = __VERIFIER_nondet_int();\n"
                             "    if (nondet) {{\n"
                             "      {0}();\n"
                             "    }}\n".format(caller + ENTRY_POINT_SUFFIX))
                fp.write("    nondet = __VERIFIER_nondet_int();\n"
                         "    if (nondet) {{\n"
                         "      {}();\n"
                         "      break;\n"
                         "    }}\n"
                         "  }}\n"
                         "}}\n".format(DEFAULT_CHECK_FINAL_STATE_FUNCTION))
                callers = [DEFAULT_MAIN]

            if strategy == SIMPLIFIED_THREADED_STRATEGY:
                fp.write("  nondet = __VERIFIER_nondet_int();\n"
                         "  switch (nondet) {\n")
                counter = 1
                for caller, params in sorted(self.entrypoints.items()):
                    if strategy == THREADED_COMBINED_STRATEGY and not params.get("races", False):
                        continue
                    fp.write("  case {0}:\n"
                             "    {1}();\n"
                             "    break;\n".format(counter, caller + ENTRY_POINT_SUFFIX))
                    counter += 1
                fp.write("  }\n"
                         "}\n\n")
                fp.write("void {0}(int argc, char *argv[]) {{\n"
                         "  int nondet;\n".format(DEFAULT_MAIN))
                fp.write("  pthread_t thread0;\n"
                         "  {0}_N(&thread0, 0, {1}, 0);\n".format(DEFAULT_THREAD_CREATE_FUNCTION,
                                                                  DEFAULT_MAIN + ENTRY_POINT_SUFFIX))
                fp.write("}\n")
                callers = [DEFAULT_MAIN]

            if strategy in [THREADED_STRATEGY]:
                counter = 1
                for caller, params in sorted(self.entrypoints.items()):
                    if params.get("races", False):
                        fp.write("  pthread_t thread{1};\n"
                                 "  {0}(&thread{1}, 0, {2}, 0);\n\n".format(DEFAULT_THREAD_CREATE_FUNCTION, counter,
                                                                            caller + ENTRY_POINT_SUFFIX))

                        counter += 1
                fp.write("}\n")
                callers = [DEFAULT_MAIN]

        return callers
