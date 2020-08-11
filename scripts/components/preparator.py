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

import json
import shutil
import sys
import tempfile

from aux.opts import *
from components import *
from components.component import Component

TAG_MODEL = "model"
TAG_RESOLVE_MISSED_PROTO = "resolve missed proto"
TAG_STRATEGY = "strategy"
TAG_FILES_SUFFIX = "files suffix"
TAG_CIL_OPTIONS = "cil options"
TAG_FAIL_ON_ANY_CIL_FAIL = "fail on any cil fail"
COMMAND_COMPILER = "command"

PREPARATION_STRATEGY_SUBSYSTEM = "subsystem"  # Take all single build commands for specific directory.
PREPARATION_STRATEGY_LIBRARY = "library"  # Create a single task for each library.
CONF_SED_AFTER_CIL = "sed after cil"
CONF_FILTERS = "filters"
CONF_UNSUPPORTED_OPTIONS = "unsupported compiler options"

STAGE_NONE = 0
STAGE_PREPROCESS = 1

DEFAULT_CIL_OPTIONS = [
    "--printCilAsIs", "--domakeCFG", "--decil", "--noInsertImplicitCasts", "--useLogicalOperators",
    "--ignore-merge-conflicts", "--no-convert-direct-calls", "--no-convert-field-offsets", "--no-split-structs",
    "--rmUnusedInlines", "--out"
]

NOT_SUPPORTED_FUNCTIONS = ["__builtin_va_arg"]
ADDED_PREFIX = "ldv_"

DEFAULT_PREP_RESULT = "build_commands.json"

EMPTY_ASPECT_TEXT = "before: file (\"$this\")\n{\n}"


class Preparator(Component):
    """
    This component is used for preparation of a verification task.
    """

    def __init__(self, install_dir, config, subdirectory_pattern=None, model=None, main_file=None,
                 common_file=None, output_file=DEFAULT_CIL_FILE, preparation_config={}, build_results=None):
        # Here we suggest 2 scenarios:
        # 1. call from launcher.py (main) - script is inside working directory already;
        # 2. manual call (aux) - script changes directory to working before creating instance of Preparator.
        # In any case script is already in working directory (root).

        super(Preparator, self).__init__(COMPONENT_PREPARATOR, config)

        if not build_results:
            sys.exit("Build results were not passed")
        self.build_results = build_results

        self.install_dir = install_dir  # Must be absolute path here.

        # Configure CIL.
        self.cil_out = self.component_config.get('cil_out', os.path.join(self.work_dir, output_file))
        cil_bin = self.get_tool_path(DEFAULT_TOOL_PATH[CIL], self.component_config.get(TAG_TOOLS, {}).get(CIL))
        cil_options = self.component_config.get(TAG_CIL_OPTIONS, DEFAULT_CIL_OPTIONS)
        self.cil_command = [cil_bin] + cil_options

        self.white_list = self.component_config.get(TAG_FILTER_WHITE_LIST, [])
        self.black_list = self.component_config.get(TAG_FILTER_BLACK_LIST, [])
        self.subdirectory_pattern = subdirectory_pattern

        # Auxiliary (optional) arguments.
        self.files_suffix = self.component_config.get(TAG_FILES_SUFFIX, None)
        self.use_cil = self.component_config.get(TAG_USE_CIL, True)
        self.max_num = self.component_config.get(TAG_MAX_FILES_NUM, sys.maxsize)
        self.compiler = self.component_config.get(TAG_PREPROCESSOR, "gcc")
        self.use_cif = bool(re.search(CIF, self.compiler))
        self.aspect = self.component_config.get(TAG_ASPECT, None)
        self.extra_opts = set(self.component_config.get(TAG_EXTRA_OPTIONS, []))
        self.unsupported_opts_regex = re.compile(r"unrecognized command line option [‘«\"](.*?)[’»\"]")
        self.resolve_missed_proto = self.component_config.get(TAG_RESOLVE_MISSED_PROTO, False)
        self.strategy = self.component_config.get(TAG_STRATEGY, PREPARATION_STRATEGY_SUBSYSTEM)
        self.fail_on_cil = self.component_config.get(TAG_FAIL_ON_ANY_CIL_FAIL, False)

        # Create working directory for this component.
        preprocess_dir = os.path.join(self.work_dir, DEFAULT_PREPROCESS_DIR)
        if not os.path.exists(preprocess_dir):
            os.makedirs(preprocess_dir, exist_ok=True)
        self.preprocessing_dir = tempfile.mkdtemp(dir=preprocess_dir)

        self.main_file = self.__get_file_for_preprocess(main_file, self.preprocessing_dir)
        spec_file = self.__get_file_for_preprocess(model, self.preprocessing_dir)
        common_file = self.__get_file_for_preprocess(common_file, self.preprocessing_dir)

        self.aux_files = {}
        for file in [self.main_file, spec_file, common_file]:
            if file:
                self.aux_files[file] = STAGE_NONE

        # some stats
        self.extracted_commands = 0
        self.complied_commands = 0
        self.processed_commands = 0
        self.temp_logs = set()
        self.libs = dict()

        self.preparation_config = preparation_config
        path_to_compilers = self.component_config.get(TAG_PATH, "")
        if os.path.exists(path_to_compilers):
            os.environ["PATH"] += os.pathsep + path_to_compilers

        # Counters for statistics.
        self.overall_build_commands = 0
        self.incorrect_build_commands = 0
        self.special_regexp_filter_build_commands = 0
        self.subsystem_filter_build_commands = 0
        self.black_list_filter_build_commands = 0
        self.build_commands = {}

    def __get_file_for_preprocess(self, file, work_dir):
        if not file:
            return None
        abs_path = os.path.join(work_dir, os.path.basename(file))
        if not os.path.exists(abs_path):
            shutil.copy(file, work_dir)
        return abs_path

    def preprocess_model_file(self, file, cif_in, cif_out, cif_args):
        file_out = file + ".i"
        cif_args = [file_out if x == cif_out else x for x in cif_args]
        cif_args = [file if x == cif_in else x for x in cif_args]

        self.logger.debug(' '.join(cif_args))
        if not self.command_caller(cif_args, self.preprocessing_dir, keep_log=False):
            return file_out
        else:
            self.logger.debug("Error in preprocessing model file %s", file_out)
            return None

    def get_first_target(self, command, tag):
        if command[tag] == [] or command[tag] is None:
            self.incorrect_build_commands += 1
            return None

        command_file = command[tag][0]

        if command_file == "0":
            self.logger.warning("Argument {0} is zero, this usually means, "
                                "that some build option is not correctly parsed,"
                                " please, check clade configuration".format(tag))
            command_file = command["in"][1]

        if command_file == "-" or command_file == "/dev/null" or command_file is None:
            self.incorrect_build_commands += 1
            return None
        elif tag == "in" and (re.search(r'\.[sS]$', command_file) or
                              re.search(r'\.o$', command_file)):
            self.incorrect_build_commands += 1
            return None
        for regexp in self.preparation_config.get(CONF_FILTERS, []):
            if re.search(regexp, command_file):
                self.special_regexp_filter_build_commands += 1
                return None

        return command_file

    def __is_skip_file(self, file):
        if self.is_auxiliary(file):
            # Do not touch aux files.
            return False
        if self.white_list:
            for elem in self.white_list:
                if re.search(elem, file):
                    # Do not touch white-listed files (overrides other excludes).
                    return False
        if self.black_list:
            for elem in self.black_list:
                if re.search(elem, file):
                    # Exclude black-listed files.
                    self.black_list_filter_build_commands += 1
                    return True
        if file in self.build_commands:
            self.build_commands[file][0] = True
        if self.subdirectory_pattern:
            if not re.search(self.subdirectory_pattern, file):
                # Exclude files for none-specified subdir.
                self.subsystem_filter_build_commands += 1
                return True
        if file in self.build_commands:
            self.build_commands[file][1] = True
        # If no regexp was applied then do not skip the file.
        return False

    def process_cc_command(self, command, source_dir):
        # Workarounds for bad cc commands

        cif_in = self.get_first_target(command, "in")
        if cif_in is None:
            self.logger.debug("Skip command due to absent in: %s", str(command))
            return -1, None
        cif_out = self.get_first_target(command, "out")
        if cif_out is None:
            if self.strategy in [PREPARATION_STRATEGY_SUBSYSTEM]:
                self.logger.debug("Skip command due to subsystem filter: %s", str(command))
                return -1, None
            counter = len(self.libs) + 1
            self.libs[counter] = []
            processed_files = []
            for cif_in in command["in"]:
                if not os.path.isabs(cif_in):
                    cif_in = os.path.normpath(os.path.join(command["cwd"], cif_in))
                cif_out = cif_in + ".i"

                ret, files = self.__process_single_cc_command(command, cif_out, cif_in, source_dir)
                if not ret:
                    self.libs[counter].append(cif_out)
                if files:
                    processed_files.extend(files)
                    self.libs[counter].extend(files)

            if self.libs[counter]:
                return 0, processed_files
            else:
                del self.libs[counter]
                return -1, None

        if self.strategy in [PREPARATION_STRATEGY_LIBRARY]:
            return -1, None
        else:
            if not os.path.isabs(cif_out):
                cif_out = os.path.normpath(os.path.join(command["cwd"], cif_out))
            if not os.path.isabs(cif_in):
                cif_in = os.path.normpath(os.path.join(command["cwd"], cif_in))
            return self.__process_single_cc_command(command, cif_out, cif_in, source_dir)

    def __process_single_cc_command(self, command, cif_out, cif_in, source_dir):
        processed_files = []

        cif_out = os.path.normpath(os.path.relpath(cif_out, start=source_dir))
        if self.__is_skip_file(cif_out):
            self.logger.debug("Skip file due to filter settings: %s", cif_out)
            return -1, None
        self.extracted_commands += 1

        if "cwd" in command:
            os.chdir(command["cwd"])
        else:
            os.chdir(source_dir)

        cif_out = os.path.normpath(os.path.join(self.preprocessing_dir, cif_out))

        os.makedirs(os.path.dirname(cif_out), exist_ok=True)

        if self.use_cif:
            # Use CIF as a compiler.
            if not self.aspect:
                self.aspect = os.path.abspath(DEFAULT_CIF_FILE)
                self.logger.warning("Aspect file was not specified for CIF, using empty aspect '{}'".
                                    format(self.aspect))
                with open(self.aspect, "w", encoding='utf8') as fa:
                    fa.write(EMPTY_ASPECT_TEXT)
            cif_args = [self.compiler,
                        "--in", cif_in,
                        "--aspect", self.aspect,
                        "--back-end", "src",
                        "--stage", "compilation",
                        "--out", cif_out]
            if self.debug:
                cif_args = cif_args + ["--debug", "ALL"]
            cif_args.append("--")
        else:
            if self.compiler == COMMAND_COMPILER:
                # Take compiler from the build command.
                compiler = command["command"]
            else:
                # Use specified compiler (GCC be default).
                compiler = self.compiler
            cif_args = [compiler, "-E", cif_in, "-o", cif_out]
        opts = command["opts"][:]
        opts.extend(self.extra_opts)
        opts = [re.sub(r'\"', r'\\"', opt) for opt in opts]
        cif_unsupported_opts = preprocessor_deps_opts + self.preparation_config.get(CONF_UNSUPPORTED_OPTIONS, [])
        opts = filter_opts(opts, cif_unsupported_opts)
        if self.use_cif:
            # noinspection PyUnresolvedReferences
            from clade.extensions.opts import filter_opts as cif_filter_opts
            opts = cif_filter_opts(opts)
        cif_args.extend(opts)

        self.logger.debug(" ".join(cif_args))

        os.chdir(source_dir)
        # Redirecting output into Pipe fails on some CIF calls
        ret = self.command_caller(cif_args, self.preprocessing_dir)

        # Add file even it will fail
        processed_files.append(cif_out)

        if not ret:
            for file, stage in self.aux_files.items():
                if stage == STAGE_NONE:
                    aux_file_out = self.preprocess_model_file(file, cif_in, cif_out, cif_args)
                    if aux_file_out:
                        if not self.__execute_cil(self.cil_out, [aux_file_out]):
                            processed_files.append(aux_file_out)
                            self.aux_files[file] = STAGE_PREPROCESS
        return ret, processed_files

    def fix_cil_file(self, cil_file):
        # Remove functions, which are not supported by CPAchecker,
        # by adding ldv_ prefix.
        for func in NOT_SUPPORTED_FUNCTIONS:
            self.exec_sed_cmd('s/{0}/{1}{0}/g'.format(func, ADDED_PREFIX), cil_file)

        for regexp in self.preparation_config.get(CONF_SED_AFTER_CIL, []):
            self.exec_sed_cmd(regexp, cil_file)

        if self.resolve_missed_proto:
            self.__resolve_missed_proto(cil_file)

    def __resolve_missed_proto(self, cil_file):
        missed_proto = dict()
        out = self.command_caller_with_output("grep -oE \"missing proto \*/(.+)\)\(\)\" {}".format(cil_file))
        for line in out.splitlines():
            line = re.sub('missing proto \*/\s+', '', line)
            line = re.sub('\)\(\)', '', line)
            missed_proto[line] = 0
        none_main_funcs = dict()
        for func in missed_proto.keys():
            out = self.command_caller_with_output("grep -oE \" {}\((.*)\)\" {}".format(func, self.main_file))
            if not out:
                self.logger.debug("Function prototype {} was not found in main file".format(func))
                none_main_funcs[func] = 0
                continue
            line = out.splitlines()[0]
            line = re.sub(' {}\('.format(func), '', line)
            line = re.sub('\)$'.format(func), '', line)
            if line:
                missed_proto[func] = line.count(", ") + 1
        for func in none_main_funcs.keys():
            out = self.command_caller_with_output("grep -oE \" {}\((.*)\)\" {}".format(func, cil_file))
            if not out:
                self.logger.warning("Function prototype {} was not found in CIL file".format(func))
                continue
            line = out.splitlines()[0]
            line = re.sub(' {}\('.format(func), '', line)
            line = re.sub('\)$'.format(func), '', line)
            if line:
                missed_proto[func] = line.count(", ") + 1
        if missed_proto:
            with open(cil_file, "a", encoding='utf8') as fp:
                fp.write("\n\n/* Adding missed function prototypes*/\n\n")
                for func, params in missed_proto.items():
                    if params == 0:
                        proto_params = "void"
                    else:
                        proto_params = "int"
                        for i in range(1, params):
                            proto_params = "{}, int".format(proto_params)
                    fp.write("extern int {}({});\n".format(func, proto_params))

            self.exec_sed_cmd('s/^(.+)missing proto \*\//\/\//g', cil_file, args='-E')

    def __print_temp_logs(self):
        contexts = set()
        for log in self.temp_logs:
            with open(log, errors='ignore') as fd:
                context = "".join(fd.readlines())
                if context not in contexts:
                    contexts.add(context)
                    print(context)

    def run_preparator(self):
        processed_files = []
        failed_files = []

        self.logger.debug("Start parsing build commands")
        prev_cwd = os.getcwd()
        for source_dir, build_commands in self.build_results.items():
            if build_commands and os.path.exists(build_commands):
                with open(build_commands, "r", errors='ignore') as bc_fh:
                    bc_json = json.load(bc_fh)
            else:
                # noinspection PyUnresolvedReferences
                from clade import Clade
                cur_dir = os.getcwd()
                os.chdir(source_dir)
                c = Clade(CLADE_WORK_DIR, CLADE_BASE_FILE)
                bc_json = c.get_compilation_cmds(with_opts=True, with_raw=True)
                os.chdir(cur_dir)

            number_of_commands = len(bc_json)
            self.overall_build_commands = number_of_commands
            if number_of_commands == 0:
                sys.exit("Specified json file doesn't contain valid cc or ld commands")
            self.logger.debug("Found {} build commands".format(number_of_commands))

            # TODO: Need to prevent none-deterministic issues.
            for command in bc_json:
                if "command" not in command:
                    sys.exit("Can't find 'command' field in the next build command: {}".format(command))
                elif "in" not in command:
                    sys.exit("Can't find 'in' field in build command: {}".format(command))
                elif "out" not in command:
                    sys.exit("Can't find 'out' field in build command: {}".format(command))

                if command['out']:
                    cmd_name = command['out'][0]
                    if not os.path.isabs(cmd_name):
                        cmd_name = os.path.normpath(os.path.join(command["cwd"], cmd_name))
                    cmd_name = os.path.normpath(os.path.relpath(cmd_name, source_dir))
                    self.build_commands[cmd_name] = [False, False, False, False]

                ret, files = self.process_cc_command(command, source_dir)
                if not ret:
                    processed_files.extend(files)
                    for file in files:
                        file = os.path.normpath(os.path.relpath(file, self.preprocessing_dir))
                        if file in self.build_commands:
                            self.build_commands[file][2] = True
                elif files:
                    failed_files.extend(files)

        for aux_file, stage in self.aux_files.items():
            if stage != STAGE_PREPROCESS:
                self.logger.critical("Auxiliary file '{}' was not prepared due to following reasons:".format(aux_file))
                self.__print_temp_logs()
                sys.exit(-1)

        self.complied_commands = len(processed_files)

        os.chdir(prev_cwd)

        if len(failed_files) > 0:
            for failed in failed_files:
                self.logger.warning("File '{}' could not be compiled".format(failed))
        if self.debug:
            preprocessed_files_dump = os.path.join(self.work_dir, "preprocessed_files.txt")
            self.logger.debug("Dump preprocessed files into %s", preprocessed_files_dump)
            with open(preprocessed_files_dump, "w") as out_fh:
                for file in processed_files:
                    out_fh.write(file + "\n")

        processed_files.sort()
        processed_files_sorted = []
        for file in processed_files:
            if self.is_auxiliary(file):
                # Put aux files to the start (they may rewrite other functions).
                processed_files_sorted.insert(0, file)
            else:
                processed_files_sorted.append(file)

        self.logger.debug("Parsing build commands is finished")
        self.logger.debug("{} files were found for further processing".format(len(processed_files_sorted)))
        return processed_files_sorted

    def is_auxiliary(self, file):
        for aux_file in self.aux_files.keys():
            if re.search(aux_file, file):
                return True
        return False

    def filter_files(self, files):
        checked_files = []
        filtered_files = []

        for line in files:
            if line in filtered_files:
                self.logger.debug("%s is already exists", line)
            else:
                filtered_files.append(line)

        self.logger.debug("Found %d files", len(filtered_files))

        if len(filtered_files) == 0:
            sys.exit("No files were successfully processed")

        if len(filtered_files) > self.max_num:
            sliced_files = filtered_files[0:self.max_num]
        else:
            sliced_files = filtered_files[0:]

        for file in sliced_files:
            if self.files_suffix:
                file_copy = file + self.files_suffix
                try:
                    shutil.copy(file, file_copy)
                except:
                    self.__on_exit()
                    sys.exit("Can not copy file '{}' to '{}'".format(file, file_copy))
                file = file_copy
            if not self.__execute_cil(self.cil_out, [file]):
                checked_files.append(file)
                file_cmd = os.path.normpath(os.path.relpath(file, self.preprocessing_dir))
                if file_cmd in self.build_commands:
                    self.build_commands[file_cmd][3] = True
            else:
                if self.fail_on_cil:
                    self.__on_exit()
                    sys.exit("Stop verification task preparation due to CIL failure")
                self.logger.warning("Skip file '%s' due to failed check", file)
                if self.is_auxiliary(file):
                    self.__on_exit()
                    sys.exit("Stop preparation due to failed check on auxiliary file")

        self.logger.debug("%d files were successfully checked", len(checked_files))

        self.processed_commands = len(checked_files)
        return checked_files

    def __execute_cil(self, output_file: str, input_files: list) -> int:
        cil_args = self.cil_command + [output_file] + input_files
        return self.command_caller(cil_args, self.preprocessing_dir)

    def __merge_cil(self, output_file: str, input_files: list) -> None:
        if self.__execute_cil(output_file, input_files):
            self.logger.critical("CIL has failed during merge on {}".format(output_file))
        else:
            self.logger.debug("CIL has merged {} files successfully {}".format(len(input_files), output_file))
            self.fix_cil_file(output_file)

    def prepare_task(self, queue=None):
        self.logger.debug("Start processing build commands")
        prepared_files = self.run_preparator()
        checked_files = self.filter_files(prepared_files)

        if self.use_cil:
            os.remove(self.cil_out)  # Remove temp files.
            if self.libs:
                for num, files in self.libs.items():
                    selected_files = []
                    for file in files:
                        if file in checked_files:
                            selected_files.append(file)
                    for file in checked_files:
                        if self.is_auxiliary(file):
                            selected_files.append(file)
                    cil_out = self.cil_out + "_{}.i".format(num)
                    self.__merge_cil(cil_out, selected_files)
            else:
                self.__merge_cil(self.cil_out, checked_files)
        else:
            pass
            # TODO: add support for none-CIL launches.

        os.chdir(self.work_dir)

        self.logger.debug("Overall build commands: {}, incorrect: {}, filtered by special regexp: {}, "
                          "filtered by black filter: {}, filtered by subsystem: {}, processed: {}".format(
            self.overall_build_commands, self.incorrect_build_commands, self.special_regexp_filter_build_commands,
            self.black_list_filter_build_commands, self.subsystem_filter_build_commands, self.extracted_commands
        ))
        self.logger.info("Successfully finished task preparation {} "
                         "(extracted commands: {}, compiled commands: {}, processed commands: {})".
                         format(self.cil_out, self.extracted_commands, self.complied_commands, self.processed_commands))
        if queue:
            results_data = self.get_component_full_stats()
            results_data[TAG_CIL_FILE] = self.cil_out
            results_file = os.path.join(self.preprocessing_dir, DEFAULT_PREP_RESULT)
            with open(results_file, 'w', encoding='utf8') as fd:
                json.dump(self.build_commands, fd, ensure_ascii=False, sort_keys=True, indent="\t")
            results_data[TAG_PREP_RESULTS] = results_file
            queue.put(results_data)

    def __on_exit(self):
        # Clean aux files.
        if os.path.exists(self.cil_out):
            os.remove(self.cil_out)

