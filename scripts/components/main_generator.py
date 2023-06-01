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

"""
Component is used for generating a file with main entry point.
"""

from components.component import Component
from models.verification_result import *

DEFAULT_TYPE = "int"
DEFAULT_VOID = "void"
DEFAULT_THREAD_CREATE_FUNCTION = "ldv_thread_create"
DEFAULT_CHECK_FINAL_STATE_FUNCTION = "ldv_check_final_state"
ARGUMENT_PREFIX = "ldv_"

# Entry-points file tags.
TAG_INCLUDE = "include"
TAG_RETURN = "return"
TAG_ARGS = "args"
TAG_STATIC_PROTOTYPE = "static prototype"
TAG_TYPE = "type"
TAG_RENAME = "rename"
TAG_SED_COMMANDS = "sed commands"
TAG_CAST = "cast"
TAG_IGNORE_PTHREAD_ATTR = "ignore pthread_attr_t"
TAG_IGNORE_ENTRYPOINT = "ignore"
TAG_NOT_IGNORE_ENTRYPOINT = "not ignore"
TAG_GLOBAL_SCOPE = "global scope"

# Config tags.
TAG_STRATEGIES = "strategies"
TAG_PRINT_PROTOTYPES = "print prototypes"
TAG_IGNORE_TYPES = "ignore types"

# Strategies.
PARTIAL_STRATEGY = "partial"
PARTIAL_EXT_ALLOCATION_STRATEGY = "partial_ext_allocation"
COMBINED_STRATEGY = "combined"
THREADED_STRATEGY = "threaded"
MAIN_GENERATOR_STRATEGIES = [PARTIAL_STRATEGY, COMBINED_STRATEGY, THREADED_STRATEGY,
                             PARTIAL_EXT_ALLOCATION_STRATEGY]


def _get_formatted_type(origin):
    formatted_type = re.sub(r' ', "_", origin)
    formatted_type = re.sub(r'\*', "", formatted_type)
    return ARGUMENT_PREFIX + formatted_type


def _simplify_type(var_type: str):
    res = re.sub(r'\s', '_', var_type)
    return re.sub(r'\*', '_pointer_', res)


def _is_pointer(var_type: str):
    return "*" in var_type


def _get_memory_allocation_function(var_type: str):
    variable_name = f"__VERIFIER_nondet_{_simplify_type(var_type)}"
    res = var_type + " " + variable_name + "() {\n"
    res = res + f"  {var_type} {variable_name};\n"
    res = res + "  " + variable_name + " = ext_allocation();\n"
    array_pointer = variable_name
    var_type = var_type.replace("*", "", 1)
    while _is_pointer(var_type):
        array_pointer = array_pointer + "[0]"
        res = res + "  " + array_pointer + " = ext_allocation();\n"
        var_type = var_type.replace("*", "", 1)
    res = res + "  return " + variable_name + ";\n"
    res = res + "}\n"
    return res


class MainGenerator(Component):
    """
    This component is used for generating file with main function, which calls specified
    entry points.
    """

    def __init__(self, config: dict, entrypoints: dict, properties_desc: PropertiesDescription):
        super().__init__(COMPONENT_MAIN_GENERATOR, config)

        # Config.
        self.ignore_types = self.component_config.get(TAG_IGNORE_TYPES, False)
        self.ignore_pthread_attr_t = self.component_config.get(TAG_IGNORE_PTHREAD_ATTR, False)
        self.print_prototypes = self.component_config.get(TAG_PRINT_PROTOTYPES, True)
        self.main_generation_strategies = {}
        for prop, strategy in properties_desc.get_property_arg_for_all(
                PROPERTY_MAIN_GENERATION_STRATEGY).items():
            if strategy:
                self.__use_strategy(strategy, prop)
                self.logger.debug(f"Use strategy {strategy} for property {prop}")

        for prop, strategy in self.component_config.get(TAG_STRATEGIES, {}).items():
            self.__use_strategy(strategy, prop)

        self.entrypoints = entrypoints
        self.callers = []
        statics = set()
        self.sed_commands = {}
        self.includes = set()
        for caller, params in sorted(self.entrypoints.items()):
            if TAG_STATIC_PROTOTYPE in params:
                statics.add(caller)
                caller += STATIC_SUFFIX
                self.entrypoints[caller] = params
            metadata = self.__get_metadata(params)
            sed_cmds = metadata.get(TAG_SED_COMMANDS, [])
            if sed_cmds:
                subsystem = metadata.get(TAG_SUBSYSTEM, DEFAULT_SUBSYSTEM)
                if subsystem not in self.sed_commands:
                    self.sed_commands[subsystem] = set()
                self.sed_commands[subsystem] = self.sed_commands[subsystem].union(set(sed_cmds))
            self.includes = self.includes.union(metadata.get(TAG_INCLUDE, set()))
            self.callers.append(caller + ENTRY_POINT_SUFFIX)

        for static in statics:
            del self.entrypoints[static]

    def __use_strategy(self, strategy: str, prop: str):
        if strategy not in MAIN_GENERATOR_STRATEGIES:
            sys.exit(f"Specified main generation strategy '{strategy}' for property '{prop}' "
                     f"does not exist")
        self.main_generation_strategies[prop] = strategy

    @staticmethod
    def __get_metadata(params: dict) -> dict:
        return params.get(TAG_METADATA, {})

    def get_strategy(self, prop: str) -> str:
        """
        Returns main generation strategy for a given property.
        """
        strategy = self.main_generation_strategies.get(prop, None)
        if not strategy:
            sys.exit(f"Main generation strategy for property {prop} was not specified")
        return strategy

    def __get_source_directories(self) -> set:
        source_dirs = set()
        for sources in self.config.get(COMPONENT_BUILDER, {}).get(TAG_SOURCES, []):
            if TAG_SOURCE_DIR in sources:
                source_dirs.add(sources.get(TAG_SOURCE_DIR))
        return source_dirs

    def process_sources(self) -> None:
        """
        Apply specific changes to source files before preparing verification tasks for
        this subsystem.
        """
        source_dirs = self.__get_source_directories()

        for caller, params in self.entrypoints.items():
            if TAG_STATIC_PROTOTYPE in params or TAG_RENAME in params:
                args = []
                args_with_types = []
                counter = 0
                for arg in params.get(TAG_ARGS, []):
                    args.append(f"arg_{counter}")
                    args_with_types.append(f"{arg.get(TAG_TYPE, DEFAULT_TYPE)} arg_{counter}")
                    counter += 1
                if not args_with_types:
                    args_with_types.append(DEFAULT_VOID)

                # Add prototype for static function.
                if TAG_STATIC_PROTOTYPE in params:
                    prototype = f"\nvoid {caller}({', '.join(args_with_types)})\n{{\n" \
                                f"  {caller[:-len(STATIC_SUFFIX)]}({', '.join(args)});\n}}\n"
                    for source_dir in source_dirs:
                        file_abs_path = os.path.join(source_dir, params[TAG_STATIC_PROTOTYPE])
                        if os.path.exists(file_abs_path):
                            if self.command_caller(f"echo '{prototype}' >> {file_abs_path}"):
                                self.logger.warning(
                                    f"Can not append lines '{prototype}' to file: {file_abs_path}")

                # Set unique name for function during merge.
                elif TAG_RENAME in params:
                    for initial_name, file_rel_path in params.get(TAG_RENAME, {}).items():
                        for source_dir in source_dirs:
                            file_abs_path = os.path.join(source_dir, file_rel_path)
                            if os.path.exists(file_abs_path):
                                self.exec_sed_cmd(f's/\\b{initial_name}\\b\\s*(/{caller}(/g',
                                                  file_abs_path)

        # Apply sed commands for the whole subsystem.
        for subsystem, regexps in self.sed_commands.items():
            for source_dir in source_dirs:
                subsystem_dir = os.path.join(source_dir, subsystem)
                if os.path.isdir(subsystem_dir):
                    for root, _, files_in in os.walk(subsystem_dir):
                        for name in files_in:
                            abs_path = os.path.join(root, name)
                            for regexp in sorted(regexps):
                                self.exec_sed_cmd(regexp, abs_path)

    def __is_entrypoint_ignored(self, params: dict, prop: str) -> bool:
        metadata = self.__get_metadata(params)
        global_ignore = metadata.get(TAG_IGNORE_ENTRYPOINT, [])
        if global_ignore:
            return prop in global_ignore and prop not in params.get(TAG_NOT_IGNORE_ENTRYPOINT, [])
        return prop in params.get(TAG_IGNORE_ENTRYPOINT, [])

    def generate_main(self, strategy: str, output_file: str, prop: str) -> list:
        """
        This function generates environment model.
        :param strategy: defines strategy for environment model generation.
        :param output_file: model will be generated in this file.
        :param prop: property to be checked.
        :return: list of all generated entrypoints, for which verifier should be launched.
        """
        callers = self.callers
        self.logger.info(f"Generating main file {output_file} using strategy {strategy}")

        with open(output_file, 'w', encoding='utf8') as file:
            # Add header files.
            if not self.ignore_types:
                for header in sorted(self.includes):
                    file.write(f"#include \"{header}\"\n")
            if strategy in [THREADED_STRATEGY]:
                file.write("typedef unsigned long int pthread_t;\n")
                if not self.ignore_pthread_attr_t:
                    file.write("union pthread_attr_t {\n"
                               "  char __size[56];\n"
                               "  long int __align;\n"
                               "};\ntypedef union pthread_attr_t pthread_attr_t;\n\n")
                file.write("int ldv_thread_create(pthread_t *thread, pthread_attr_t const *attr,"
                           "                      void *(*start_routine)(void *), void *arg);\n\n"
                           "int ldv_thread_join(pthread_t thread, void **retval);\n\n"
                           "int ldv_thread_create_N(pthread_t **thread, pthread_attr_t const *attr,"
                           "                        void *(*start_routine)(void *), void *arg);\n\n"
                           "int ldv_thread_join_N"
                           "(pthread_t **thread, void (*start_routine)(void *));\n\n")
            file.write(f"\n/*This is generated main function*/\n\n"
                       f"void {DEFAULT_CHECK_FINAL_STATE_FUNCTION}(void);\n\n")

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
                        var_name = _get_formatted_type(var_type) + "_" + caller + "_" + str(i)
                        if re.search(r' \*', var_type):
                            # Already has valuable space
                            var_def = var_type + var_name
                        else:
                            var_def = var_type + " " + var_name

                    global_scope = arg.get(TAG_GLOBAL_SCOPE, True)
                    is_cast = arg.get(TAG_CAST, True)
                    if global_scope:
                        file.write(var_def + ";\n")
                        if var_type not in nondet_funcs:
                            nondet_funcs.add(var_type)
                            if strategy == PARTIAL_EXT_ALLOCATION_STRATEGY and \
                                    _is_pointer(var_type):
                                file.write(_get_memory_allocation_function(var_type))
                            else:
                                file.write(
                                    f"extern {var_type} "
                                    f"__VERIFIER_nondet_{_simplify_type(var_type)}();\n")
                        if is_cast:
                            var_def = var_name + f" = ({var_type})__VERIFIER_nondet_" \
                                                 f"{_simplify_type(var_type)}();\n"
                        else:
                            var_def = var_name + f" = __VERIFIER_nondet_" \
                                                 f"{_simplify_type(var_type)}();\n"
                        local_var_defs.append(var_def)
                    else:
                        if strategy == PARTIAL_EXT_ALLOCATION_STRATEGY and _is_pointer(var_type):
                            if var_type not in nondet_funcs:
                                nondet_funcs.add(var_type)
                                file.write(_get_memory_allocation_function(var_type))
                            var_def = var_def + f" = __VERIFIER_nondet_{_simplify_type(var_type)}()"
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
                    file.write(f"extern {ret_type} {caller}({arg_def_str});\n")

                if strategy in [THREADED_STRATEGY]:
                    caller_args = DEFAULT_VOID + "* arg"
                    ret_caller_type = DEFAULT_VOID + "*"
                else:
                    caller_args = DEFAULT_VOID
                    ret_caller_type = DEFAULT_VOID
                file.write(f"/* ENVIRONMENT_MODEL {caller}{ENTRY_POINT_SUFFIX} generated main "
                           f"function */\n")
                file.write(f"{ret_caller_type} {caller}{ENTRY_POINT_SUFFIX}({caller_args}) {{\n")

                for local_var in local_var_defs:
                    file.write(f"  {local_var}")

                file.write(f"  {caller}({', '.join(arg_names)});\n")
                if strategy in [PARTIAL_STRATEGY, PARTIAL_EXT_ALLOCATION_STRATEGY]:
                    file.write(f"  {DEFAULT_CHECK_FINAL_STATE_FUNCTION}();\n")
                file.write("}\n\n")

            file.write("extern int __VERIFIER_nondet_int();\n")

            if strategy not in [PARTIAL_STRATEGY, PARTIAL_EXT_ALLOCATION_STRATEGY]:
                file.write(f"/* ENVIRONMENT_MODEL {DEFAULT_MAIN} generated main function */\n")
                file.write(f"void {DEFAULT_MAIN}(int argc, char *argv[]) {{\n  int nondet;\n")

            if strategy in [COMBINED_STRATEGY]:
                file.write("  while (1) {{\n")
                for caller, params in sorted(self.entrypoints.items()):
                    if self.__is_entrypoint_ignored(params, prop):
                        continue
                    file.write(f"    nondet = __VERIFIER_nondet_int();\n"
                               f"    if (nondet) {{\n"
                               f"      {caller + ENTRY_POINT_SUFFIX}();\n"
                               f"    }}\n")
                file.write(f"    nondet = __VERIFIER_nondet_int();\n"
                           f"    if (nondet) {{\n"
                           f"      {DEFAULT_CHECK_FINAL_STATE_FUNCTION}();\n"
                           f"      break;\n"
                           f"    }}\n"
                           f"  }}\n"
                           f"}}\n")
                callers = [DEFAULT_MAIN]

            if strategy in [THREADED_STRATEGY]:
                counter = 1
                for caller, params in sorted(self.entrypoints.items()):
                    if not self.__is_entrypoint_ignored(params, prop):
                        file.write(f"  pthread_t thread{counter};\n"
                                   f"  {DEFAULT_THREAD_CREATE_FUNCTION}(&thread{counter}, 0, "
                                   f"{caller + ENTRY_POINT_SUFFIX}, 0);\n\n")

                        counter += 1
                file.write("}\n")
                callers = [DEFAULT_MAIN]

        return callers
