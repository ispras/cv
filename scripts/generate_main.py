#!/usr/bin/python3

import json
import os
import re

from component import Component
from config import *

DEFAULT_TYPE = "int"
DEFAULT_THREAD_CREATE_FUNCTION = "ldv_thread_create"
DEFAULT_CHECK_FINAL_STATE_FUNCTION = "ldv_check_final_state"
ARGUMENT_PREFIX = "ldv_"
IGNORE_TYPES = False  # if true, then callers arguments type will be ignored (all arguments will get default type)
PRINT_PROTOTYPES = True
STATIC_SUFFIX = "_static"

TAG_STRATEGY = "strategy"
TAG_INPUT_FILE = "input"
TAG_OUTPUT_FILE = "output"
TAG_STATIC_PROTOTYPE = "static prototype"

IS_LOCAL = False


def get_formatted_type(origin):
    formatted_type = re.sub(r' ', "_", origin)
    formatted_type = re.sub(r'\*', "", formatted_type)
    return ARGUMENT_PREFIX + formatted_type


def simplify_type(var_type: str):
    res = re.sub(r'\s', '_', var_type)
    return re.sub(r'\*', '_pointer_', res)


# TODO: create new component for this functionality.
def generate_main(strategy: str, input_file: str, output_file: str, component: Component):
    """
    This function generates environment model.
    :param strategy: defines strategy for environment model generation.
    :param input_file: contains description of entrypoints.
    :param output_file: model will be generated in this file.
    :param component: component, which is calling this function.
    :return: list of all generated entrypoints, for which verifier should be launched.
    """

    callers = []
    with open(input_file, errors='ignore') as data_file:
        data = json.load(data_file)
        entrypoints = data.get("entrypoints")
        statics = set()
        metadata = data.get("metadata", {})

        for caller, params in sorted(entrypoints.items()):
            if TAG_STATIC_PROTOTYPE in params:
                if not os.path.exists(output_file):
                    add_static_prototypes(caller, params, component)
                statics.add(caller)
                caller += STATIC_SUFFIX
                entrypoints[caller] = params
            callers.append(caller + ENTRY_POINT_SUFFIX)

        for static in statics:
            del entrypoints[static]

    with open(output_file, 'w', encoding='utf8') as fp:

        # Add header files.
        if not IGNORE_TYPES:
            for header in metadata.get("include", []):
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
        for caller, params in entrypoints.items():
            ret_type = params.get('return', "void")
            arguments = params.get('args', [])
            arg_names = []
            arg_defs = []
            arg_types = []
            local_var_defs = []
            i = 0
            for arg in arguments:
                if IGNORE_TYPES:
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
                    var_def = var_name + " = ({})__VERIFIER_nondet_{}();\n".format(var_type, simplify_type(var_type))
                    local_var_defs.append(var_def)
                else:
                    local_var_defs.append(var_def + ";\n")
                arg_names.append(var_name)
                arg_defs.append(var_def)
                arg_types.append(var_type)
                i += 1

            if PRINT_PROTOTYPES:
                if arg_types:
                    arg_def_str = ", ".join(arg_types)
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


def get_source_directories(component: Component) -> set:
    source_dirs = set()
    for sources in component.config.get(COMPONENT_BUILDER, {}).get(TAG_SOURCES, []):
        if TAG_SOURCE_DIR in sources:
            source_dirs.add(sources.get(TAG_SOURCE_DIR))
    return source_dirs


def add_static_prototypes(caller: str, params: dict, component: Component) -> None:
    args = []
    args_with_types = []
    counter = 0
    for arg in params.get('args', []):
        args.append("arg_{}".format(counter))
        args_with_types.append("{} arg_{}".format(arg, counter))
        counter += 1
    if not args_with_types:
        args_with_types.append("void")
    static_declaration = "\nvoid {}({})\n{{\n  {}({});\n}}\n".format(caller + STATIC_SUFFIX, ", ".join(args_with_types),
                                                                     caller, ", ".join(args))
    for source_dir in get_source_directories(component):
        name = os.path.join(source_dir, params.get(TAG_STATIC_PROTOTYPE))
        if os.path.exists(name):
            if component.command_caller("echo '{}' >> {}".format(static_declaration, name)):
                component.logger.warning("Can not append lines '{}' to file: {}".format(static_declaration, name))


""" Not supported
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
"""
