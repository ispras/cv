# Default location of additional tools.
CIL = "cil"
WEB_INTERFACE = "klever"
BENCHEXEC = "benchexec"
CPACHECKER = "cpachecker"
UNREACHABILITY = "unreachability"
MEMSAFETY = "memsafety"
COVERAGE = "coverage"
RACES = "races"
DEADLOCK_AUX_DISPATCH = "sync:deadlocks:dispatch"
DEADLOCK_AUX_CIRCULAR_KM = "sync:deadlocks:circular:kern&mutex"
DEADLOCK_AUX_CIRCULAR_KS = "sync:deadlocks:circular:kern&spin"
DEADLOCK_AUX_CIRCULAR_MS = "sync:deadlocks:circular:mutex&spin"
DEADLOCK_SUB_PROPERTIES = [
    DEADLOCK_AUX_DISPATCH,
    DEADLOCK_AUX_CIRCULAR_KM,
    DEADLOCK_AUX_CIRCULAR_KS,
    DEADLOCK_AUX_CIRCULAR_MS
]
DEADLOCK = "deadlocks"
TERMINATION = "termination"
CIF = "cif"
CLADE = "clade"
CLADE_INTERCEPT = "clade-intercept"
CLADE_CC = "clade-cc"
CLADE_CALLGRAPH = "clade-callgraph"
UPLOADER = "uploader"
DEFAULT_TOOL_PATH = {
    CIL: ["cil/obj/x86_LINUX/cilly.asm.exe", "cil/bin/cilly.native"],
    WEB_INTERFACE: "klever/core",
    UPLOADER: "klever/utils/bin/upload-reports.py",
    BENCHEXEC: "benchexec/bin",
    CPACHECKER: {
        UNREACHABILITY: "ldv-bam/scripts",
        MEMSAFETY: "trunk/scripts",
        COVERAGE: "ldv-bam/scripts",
        RACES: "CPALockator-combat-mode/scripts",
        DEADLOCK: "CPALockator-combat-mode/scripts"
    },
    CIF: "cif/bin",
}
DEFAULT_CPACHECKER_CLOUD = {
    UNREACHABILITY: "ldv-bam",
    MEMSAFETY: "trunk",
    COVERAGE: "ldv-bam",
    RACES: "CPALockator-combat-mode",
    DEADLOCK_AUX_DISPATCH: "CPALockator-combat-mode",
    DEADLOCK_AUX_CIRCULAR_KM: "CPALockator-combat-mode",
    DEADLOCK_AUX_CIRCULAR_KS: "CPALockator-combat-mode",
    DEADLOCK_AUX_CIRCULAR_MS: "CPALockator-combat-mode",
}
VERIFIER_MODES = [UNREACHABILITY, MEMSAFETY, COVERAGE, RACES, TERMINATION] + DEADLOCK_SUB_PROPERTIES

# Components.
COMPONENT_MAIN_GENERATOR = "Main_generator"
COMPONENT_PREPARATOR = "Preparator"
COMPONENT_LAUNCHER = "Launcher"
COMPONENT_EXPORTER = "Exporter"
COMPONENT_MEA = "MEA"
COMPONENT_QUALIFIER = "Qualifier"
COMPONENT_BUILDER = "Builder"

# Preset rules
RULE_COVERAGE = "cov"
RULE_RACES = "sync:races"
RULE_DEADLOCK = "sync:deadlocks"
RULE_MEMSAFETY = "smg"
RULE_TERMINATION = "termination"  # aux rule so far.

# Main generator.
DEFAULT_MAIN_FILE = "main_generated.c"
DEFAULT_MAIN = "ldv_main_generated"
PARTIAL_STRATEGY = "partial"
COMBINED_STRATEGY = "combined"
THREADED_STRATEGY = "threaded"
SIMPLIFIED_THREADED_STRATEGY = "simplified_threaded"
THREADED_STRATEGY_NONDET = "threaded_nondet"
THREADED_COMBINED_STRATEGY = "threaded_combined"
MAIN_GENERATOR_STRATEGIES = [PARTIAL_STRATEGY, COMBINED_STRATEGY, THREADED_STRATEGY, THREADED_STRATEGY_NONDET,
                             THREADED_COMBINED_STRATEGY, SIMPLIFIED_THREADED_STRATEGY]


TAG_DIRS = "dirs"
TAG_DIRS_WORK = "work"
TAG_DIRS_INSTALL = "install"
TAG_DIRS_ENTRYPOINTS = "entypoints"
TAG_DIRS_INSTRUMENTED_RULES = "instrumented_rules"
TAG_DIRS_RESULTS = "results"

TAG_CPU_TIME = "cpu"
TAG_WALL_TIME = "wall"
TAG_MEMORY_USAGE = "memory"
TAG_EXITCODE = "exit code"

TAG_BUILD_COMMANDS = "build_commands"
TAG_DEBUG = "debug"
TAG_TOOLS = "tools"
TAG_FILTERS = "filters"

TAG_SOURCE_DIR = "source dir"
TAG_SYSTEM_ID = "system"
TAG_CLADE_CONF = "clade config"
TAG_MAKE_COMMAND = "make command"
TAG_FAIL_IF_FAILURE = "fail if build fails"

BUSY_WAITING_INTERVAL = 1

DEFAULT_PREPROCESS_DIR = "preprocess"
TAG_FILTER_WHITE_LIST = "filter white list"
TAG_FILTER_BLACK_LIST = "filter black list"
TAG_USE_CIL = "use cil"
TAG_MAX_FILES_NUM = "max files"
TAG_PREPROCESSOR = "preprocessor"
TAG_ASPECT = "aspect"
TAG_EXTRA_OPTIONS = "extra options"
DEFAULT_EXPORT_DIR = "export"

COMMON_HEADER_FOR_RULES = "common.h"

DEFAULT_CIL_FILE = "cil.i"

TERMINATION_SUCCESS = "SUCCESS"
VERDICT_SAFE = "TRUE"
VERDICT_UNSAFE = "FALSE"
VERDICT_UNKNOWN = "UNKNOWN"

MEA_DEFAULT_FILTER_OTHERS = "model_functions"
MEA_DEFAULT_FILTER_RACES = "model_functions"
MEA_DEFAULT_FILTER_SMG = "model_functions_smg"

DEFAULT_BUILD_COMMANDS_FILE = "cmds.json"

ENTRY_POINT_SUFFIX = "_caller"

JSON_EXTENSION = ".json"

PREPARATOR_LOG_FILE = "log.txt"
TAG_LOG_FILE = "log"

TAG_METADATA = "metadata"
TAG_SUBSYSTEM = "subsystem"

CLADE_WORK_DIR = "clade-work-dir"
CLADE_BASE_FILE = "cmds.txt"
CLADE_DEFAULT_CONFIG_FILE = "clade_conf.json"
