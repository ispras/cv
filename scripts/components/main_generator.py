#
# CV is a framework for continuous verification.
#
# Copyright (c) 2018-2019 ISP RAS (http://www.ispras.ru)
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

from components.component import Component
from models.verification_result import *

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
TAG_TYPE = "type"
TAG_RENAME = "rename"
TAG_SED_COMMANDS = "sed commands"
TAG_CAST = "cast"
TAG_IGNORE_PTHREAD_ATTR = "ignore pthread_attr_t"

# Config tags.
TAG_STRATEGIES = "strategies"
TAG_PRINT_PROTOTYPES = "print prototypes"
TAG_IGNORE_TYPES = "ignore types"

# Strategies.
PARTIAL_STRATEGY = "partial"
PARTIAL_EXT_ALLOCATION_STRATEGY = "partial_ext_allocation"
COMBINED_STRATEGY = "combined"
THREADED_STRATEGY = "threaded"
MAIN_GENERATOR_STRATEGIES = [PARTIAL_STRATEGY, COMBINED_STRATEGY, THREADED_STRATEGY, PARTIAL_EXT_ALLOCATION_STRATEGY]


def get_formatted_type(origin):
    formatted_type = re.sub(r' ', "_", origin)
    formatted_type = re.sub(r'\*', "", formatted_type)
    return ARGUMENT_PREFIX + formatted_type


def simplify_type(var_type: str):
    res = re.sub(r'\s', '_', var_type)
    return re.sub(r'\*', '_pointer_', res)


def is_pointer(var_type: str):
    return "*" in var_type


def get_memory_allocation_function(var_type: str):
    variable_name = "__VERIFIER_nondet_{}".format(simplify_type(var_type))
    res = var_type + " " + variable_name + "() {\n"
    res = res + "  {} {};\n".format(var_type, variable_name)
    res = res + "  " + variable_name + " = ext_allocation();\n"
    array_pointer = variable_name
    var_type = var_type.replace("*", "", 1)
    while is_pointer(var_type):
        array_pointer = array_pointer + "[0]"
        res = res + "  " + array_pointer + " = ext_allocation();\n"
        var_type = var_type.replace("*", "", 1)
    res = res + "  return " + variable_name + ";\n"
    res = res + "}\n"
    return res


class MainGenerator(Component):
    """
    This component is used for generating file with main function, which calls specified entry points.
    """

    def __init__(self, config: dict, input_file: str, properties_desc: PropertiesDescription):
        super(MainGenerator, self).__init__(COMPONENT_MAIN_GENERATOR, config)

        # Config.
        self.ignore_types = self.component_config.get(TAG_IGNORE_TYPES, False)
        self.ignore_pthread_attr_t = self.component_config.get(TAG_IGNORE_PTHREAD_ATTR, False)
        self.print_prototypes = self.component_config.get(TAG_PRINT_PROTOTYPES, True)
        self.main_generation_strategies = {}
        for prop, strategy in properties_desc.get_property_arg_for_all(PROPERTY_MAIN_GENERATION_STRATEGY).items():
            if strategy:
                self.__use_strategy(strategy, prop)
                self.logger.debug("Use strategy {} for property {}".format(strategy, prop))

        for prop, strategy in self.component_config.get(TAG_STRATEGIES, {}).items():
            self.__use_strategy(strategy, prop)

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

    def __use_strategy(self, strategy: str, prop: str):
        if strategy not in MAIN_GENERATOR_STRATEGIES:
            sys.exit("Specified main generation strategy '{}' for property '{}' does not exist".format(strategy, prop))
        self.main_generation_strategies[prop] = strategy

    def get_strategy(self, prop: str) -> str:
        strategy = self.main_generation_strategies.get(prop, None)
        if not strategy:
            sys.exit("Main generation strategy for property {} was not specified".format(prop))
        return strategy

    def __get_source_directories(self) -> set:
        source_dirs = set()
        for sources in self.config.get(COMPONENT_BUILDER, {}).get(TAG_SOURCES, []):
            if TAG_SOURCE_DIR in sources:
                source_dirs.add(sources.get(TAG_SOURCE_DIR))
        return source_dirs

    def process_sources(self) -> None:
        """
        Apply specific changes to source files before preparing verification tasks for this subsystem.
        """
        source_dirs = self.__get_source_directories()

        for caller, params in self.entrypoints.items():
            if TAG_STATIC_PROTOTYPE in params or TAG_RENAME in params:
                args = []
                args_with_types = []
                counter = 0
                for arg in params.get(TAG_ARGS, []):
                    args.append("arg_{}".format(counter))
                    args_with_types.append("{} arg_{}".format(arg.get(TAG_TYPE, DEFAULT_TYPE), counter))
                    counter += 1
                if not args_with_types:
                    args_with_types.append(DEFAULT_VOID)

                # Add prototype for static function.
                if TAG_STATIC_PROTOTYPE in params:
                    prototype = "\nvoid {}({})\n{{\n  {}({});\n}}\n".format(caller, ", ".join(args_with_types),
                                                                            caller[:-len(STATIC_SUFFIX)],
                                                                            ", ".join(args))
                    for source_dir in source_dirs:
                        file_abs_path = os.path.join(source_dir, params[TAG_STATIC_PROTOTYPE])
                        if os.path.exists(file_abs_path):
                            if self.command_caller("echo '{}' >> {}".format(prototype, file_abs_path)):
                                self.logger.warning("Can not append lines '{}' to file: {}".
                                                    format(prototype, file_abs_path))

                # Set unique name for function during merge.
                elif TAG_RENAME in params:
                    for initial_name, file_rel_path in params.get(TAG_RENAME, {}).items():
                        for source_dir in source_dirs:
                            file_abs_path = os.path.join(source_dir, file_rel_path)
                            if os.path.exists(file_abs_path):
                                self.exec_sed_cmd('s/\\b{}\\b\\s*(/{}(/g'.format(initial_name, caller), file_abs_path)

        # Apply sed commands for the whole subsystem.
        for regexp in self.metadata.get(TAG_SED_COMMANDS, []):
            for source_dir in source_dirs:
                subsystems = self.metadata.get(TAG_SUBSYSTEM, ".")
                if type(subsystems) == str:
                    subsystems = [subsystems]
                for subsystem in subsystems:
                    subsystem_dir = os.path.join(source_dir, subsystem)
                    if os.path.isdir(subsystem_dir):
                        for root, dirs, files_in in os.walk(subsystem_dir):
                            for name in files_in:
                                file = os.path.join(root, name)
                                self.exec_sed_cmd(regexp, file)

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
            if strategy in [THREADED_STRATEGY]:
                fp.write("typedef unsigned long int pthread_t;\n")
                if not self.ignore_pthread_attr_t:
                    fp.write("union pthread_attr_t {\n"
                             "  char __size[56];\n"
                             "  long int __align;\n"
                             "};\ntypedef union pthread_attr_t pthread_attr_t;\n\n")
                fp.write("int ldv_thread_create(pthread_t *thread, pthread_attr_t const *attr,"
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
                        var_type = arg.get(TAG_TYPE, DEFAULT_TYPE)
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
                    is_cast = arg.get(TAG_CAST, True)
                    if global_scope:
                        fp.write(var_def + ";\n")
                        if var_type not in nondet_funcs:
                            nondet_funcs.add(var_type)
                            if strategy == PARTIAL_EXT_ALLOCATION_STRATEGY and is_pointer(var_type):
                                fp.write(get_memory_allocation_function(var_type))
                            else:
                                fp.write(
                                    "extern {} __VERIFIER_nondet_{}();\n".format(var_type, simplify_type(var_type)))
                        if is_cast:
                            var_def = var_name + " = ({})__VERIFIER_nondet_{}();\n".format(var_type,
                                                                                           simplify_type(var_type))
                        else:
                            var_def = var_name + " = __VERIFIER_nondet_{}();\n".format(simplify_type(var_type))
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

                if strategy in [THREADED_STRATEGY]:
                    caller_args = DEFAULT_VOID + "* arg"
                    ret_caller_type = DEFAULT_VOID + "*"
                else:
                    caller_args = DEFAULT_VOID
                    ret_caller_type = DEFAULT_VOID
                fp.write("/* ENVIRONMENT_MODEL {}{} generated main function */\n".format(caller, ENTRY_POINT_SUFFIX))
                fp.write("{0} {1}{2}({3}) {{\n".format(ret_caller_type, caller, ENTRY_POINT_SUFFIX, caller_args))

                for local_var in local_var_defs:
                    fp.write("  {0}".format(local_var))

                fp.write("  {0}({1});\n".format(caller, ", ".join(arg_names)))
                if strategy in [PARTIAL_STRATEGY, PARTIAL_EXT_ALLOCATION_STRATEGY]:
                    fp.write("  {}();\n".format(DEFAULT_CHECK_FINAL_STATE_FUNCTION))
                fp.write("}\n\n")

            fp.write("extern int __VERIFIER_nondet_int();\n")

            if strategy not in [PARTIAL_STRATEGY, PARTIAL_EXT_ALLOCATION_STRATEGY]:
                fp.write("/* ENVIRONMENT_MODEL {} generated main function */\n".format(DEFAULT_MAIN))
                fp.write("void {0}(int argc, char *argv[]) {{\n"
                         "  int nondet;\n".format(DEFAULT_MAIN))

            if strategy in [COMBINED_STRATEGY]:
                fp.write("  while (1) {{\n".format(DEFAULT_MAIN))
                for caller, params in sorted(self.entrypoints.items()):
                    if not params.get("races", False):
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
