#!/usr/bin/python3

import argparse
import json
import os
import sys
import re

from config import *

DEFAULT_TYPE = "int"
DEFAULT_THREAD_CREATE_FUNCTION = "ldv_thread_create"
DEFAULT_CHECK_FINAL_STATE_FUNCTION = "ldv_check_final_state"
ARGUMENT_PREFIX = "arg__"
IGNORE_TYPES = False  # if true, then callers arguments type will be ignored (all arguments will get default type)
PRINT_PROTOTYPES = False

TAG_STRATEGY = "strategy"
TAG_INPUT_FILE = "input"
TAG_OUTPUT_FILE = "output"

IS_LOCAL = False


def getFormattedType(origin):
    formatted_type = re.sub(r' ', "_", origin)
    formatted_type = re.sub(r'\*', "", formatted_type)
    return formatted_type


def simplify_type(var_type: str):
    res = re.sub(r'\s', '_', var_type)
    return re.sub(r'\*', '_pointer_', res)


def generate_main(strategy: str, input_file: str, output_file: str):
    """
    This function generates environment model.
    :param strategy: defines strategy for environment model generation.
    :param input_file: contains description of entrypoints.
    :param output_file: model will be generated in this file.
    :return: list of all generated entrypoints, for which verifier should be launched.
    """

    callers = []
    with open(input_file, errors='ignore') as data_file:
        data = json.load(data_file)
        entrypoints = data.get("entrypoints")
        metadata = data.get("metadata", {})

        for caller, params in sorted(entrypoints.items()):
            callers.append(caller + ENTRY_POINT_SUFFIX)

    with open(output_file, 'w', encoding='utf8') as fp:

        # Add header files.
        if not IGNORE_TYPES:
            for header in metadata.get("include", []):
                fp.write("#include \"{}\"\n".format(header))
        if strategy in [THREADED_STRATEGY, THREADED_STRATEGY_NONDET, SIMPLIFIED_THREADED_STRATEGY]:
            fp.write("#include <pthread.h>\n")
        fp.write("\n/*This is generated main function*/\n\n"
                 "void {}(void);\n\n".format(DEFAULT_CHECK_FINAL_STATE_FUNCTION))

        # Parsing function definition.
        # Do not print in file, we do not know: are the arguments local or not

        nondet_funcs = set()
        for caller, params in entrypoints.items():
            ret_type = params.get('return', "void")
            arguments = params.get('args', [])
            arg_names = []
            arg_defs = []
            local_var_defs = []
            i = 0
            for arg in arguments:
                if IGNORE_TYPES:
                    var_type = DEFAULT_TYPE
                else:
                    var_type = arg.get('type', DEFAULT_TYPE)
                if re.search(r'\$', var_type):
                    #Complicated type like function pointer - just replace $ to a caller
                    var_name = "complicated_type_" + caller + "_" + str(i)
                    #Do not format type and use it as it is
                    var_def = re.sub(r'\$', var_name, var_type)
                else:
                    var_name = getFormattedType(var_type) + "_" + caller + "_" + str(i)
                    if re.search(r' \*', var_type):
                        #Already has valuable space
                        var_def = var_type + var_name
                    else:
                        var_def = var_type + " " + var_name

                global_scope = arg.get('global scope', True)
                if global_scope:
                    fp.write(var_def + ";\n")
                    nondet_funcs.add(var_type)
                    var_def = var_name + " = ({})__VERIFIER_nondet_{}();\n".format(var_type, simplify_type(var_type))
                    local_var_defs.append(var_def)
                else:
                    local_var_defs.append(var_def + ";\n")
                arg_names.append(var_name)
                arg_defs.append(var_def)
                i += 1

            if PRINT_PROTOTYPES:
                if arg_defs:
                    arg_def_str = ", ".join(arg_defs)
                else:
                    arg_def_str = "void"
                fp.write("extern {0} {1}({2});\n".format(ret_type, caller, arg_def_str))
            
            if strategy in [THREADED_STRATEGY, THREADED_STRATEGY_NONDET]:
                caller_args = "void* arg"
                ret_caller_type = "void*"
            else:
                caller_args = "void"
                ret_caller_type = "void"
            fp.write("{0} {1}{2}({3}) {{\n".format(ret_caller_type, caller, ENTRY_POINT_SUFFIX, caller_args))

            for local_var in local_var_defs:
                fp.write("  {0}".format(local_var))

            fp.write("  {0}({1});\n".format(caller, ", ".join(arg_names)))
            if strategy == PARTIAL_STRATEGY:
                fp.write("  {}();\n".format(DEFAULT_CHECK_FINAL_STATE_FUNCTION))
            fp.write("}\n\n")

        fp.write("extern int __VERIFIER_nondet_int();\n")
        for var_type in nondet_funcs:
            fp.write("extern {} __VERIFIER_nondet_{}();\n".format(var_type, simplify_type(var_type)))

        if strategy in [SIMPLIFIED_THREADED_STRATEGY]:
            fp.write("void* {0}(void *) {{\n"
                     "  int nondet;\n".format(DEFAULT_MAIN + ENTRY_POINT_SUFFIX))
        elif strategy not in [PARTIAL_STRATEGY]:
            fp.write("void {0}(int argc, char *argv[]) {{\n"
                     "  int nondet;\n".format(DEFAULT_MAIN))

        if strategy in [COMBINED_STRATEGY, THREADED_COMBINED_STRATEGY]:
            fp.write("  while (1) {{\n".format(DEFAULT_MAIN))
            for caller, params in sorted(entrypoints.items()):
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
            for caller, params in sorted(entrypoints.items()):
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
            for caller, params in sorted(entrypoints.items()):
                if params.get("races", False):
                    fp.write("  pthread_t thread{1};\n"
                             "  {0}(&thread{1}, 0, {2}, 0);\n\n".format(DEFAULT_THREAD_CREATE_FUNCTION, counter,
                                                                        caller + ENTRY_POINT_SUFFIX))

                    counter += 1
            fp.write("}\n")
            callers = [DEFAULT_MAIN]

    return callers


if __name__ == '__main__':
    # Get config, that relates to this component. Since this is not main scenario, fail if something specified wrong.
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", metavar="PATH", help="set PATH to configuration", required=True)
    options = parser.parse_args()

    with open(options.config) as data_file:
        config = json.load(data_file)

    main_config = config[COMPONENT_MAIN_GENERATOR]
    strategy = main_config[TAG_STRATEGY]
    if strategy not in MAIN_GENERATOR_STRATEGIES:
        sys.exit("Wrong strategy specified: {0}".format(strategy))
    input_file = os.path.abspath(main_config[TAG_INPUT_FILE])
    output_file = main_config.get(TAG_OUTPUT_FILE, DEFAULT_MAIN_FILE)

    work_dir = config[TAG_DIRS][TAG_DIRS_WORK]
    os.chdir(work_dir)

    generated_entrypoints = generate_main(strategy, input_file, output_file)
    print("Generated main file with {0} entrypoints:".format(len(generated_entrypoints)))
    for caller in generated_entrypoints:
        print(caller)
