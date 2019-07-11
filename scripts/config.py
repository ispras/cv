# Default location of additional tools.
CIL = "cil"
ET_LIB = "klever"
ET_HTML_LIB = "et html"
BENCHEXEC = "benchexec"
CPACHECKER = "cpachecker"
UNREACHABILITY = "unreachability"
MEMSAFETY = "memsafety"
COVERAGE = "coverage"
RACES = "races"
DEADLOCK_AUX_DISPATCH_SPIN = "sync:deadlocks:dispatch:spin"
DEADLOCK_AUX_DISPATCH_MUTEX = "sync:deadlocks:dispatch:mutex"
DEADLOCK_AUX_CIRCULAR_MS = "sync:deadlocks:circular:mutex&spin"
DEADLOCK_SUB_PROPERTIES = [
    DEADLOCK_AUX_DISPATCH_MUTEX,
    DEADLOCK_AUX_DISPATCH_SPIN,
    DEADLOCK_AUX_CIRCULAR_MS
]
DEADLOCK = "deadlocks"
TERMINATION = "termination"
CIF = "cif"
CLADE = "clade"
UPLOADER = "uploader"
DEFAULT_TOOL_PATH = {
    CIL: ["astraver-cil/bin/toplevel.opt", "cil/obj/x86_LINUX/cilly.asm.exe", "cil/bin/cilly.native"],
    ET_LIB: "klever/core",
    ET_HTML_LIB: "klever/bridge",
    UPLOADER: "klever/utils/bin/upload-reports.py",
    BENCHEXEC: "benchexec/bin",
    CPACHECKER: {
        UNREACHABILITY: "unreach/scripts",
        MEMSAFETY: "smg/scripts",
        COVERAGE: "unreach/scripts",
        RACES: "sync/scripts",
        DEADLOCK: "sync/scripts"
    },
    CIF: "cif/bin",
}
DEFAULT_CPACHECKER_CLOUD = {
    UNREACHABILITY: "unreach",
    MEMSAFETY: "smg",
    COVERAGE: "unreach",
    RACES: "sync",
    DEADLOCK_AUX_DISPATCH_MUTEX: "sync",
    DEADLOCK_AUX_DISPATCH_SPIN: "sync",
    DEADLOCK_AUX_CIRCULAR_MS: "sync",
}
VERIFIER_MODES = [UNREACHABILITY, MEMSAFETY, COVERAGE, RACES, TERMINATION] + DEADLOCK_SUB_PROPERTIES

# Components.
COMPONENT_MAIN_GENERATOR = "Generator"
COMPONENT_PREPARATOR = "Preparator"
COMPONENT_LAUNCHER = "Launcher"
COMPONENT_EXPORTER = "Exporter"
COMPONENT_MEA = "MEA"
COMPONENT_QUALIFIER = "Qualifier"
COMPONENT_BUILDER = "Builder"
COMPONENT_COVERAGE = "Coverage"

# Preset rules
RULE_COVERAGE = "cov"
RULE_RACES = "sync:races"
RULE_DEADLOCK = "sync:deadlocks"
RULE_MEMSAFETY = "smg"
RULE_TERMINATION = "termination"  # aux rule so far.
RULE_COV_AUX_RACES = "cov_races"
RULE_COV_AUX_OTHER = "cov_other"


# Main generator.
DEFAULT_MAIN = "ldv_main_generated"

TAG_DIRS = "dirs"
TAG_DIRS_WORK = "work"
TAG_DIRS_RESULTS = "results"

TAG_CPU_TIME = "cpu"
TAG_WALL_TIME = "wall"
TAG_MEMORY_USAGE = "memory"
TAG_EXITCODE = "exit code"
TAG_CIL_FILE = "cil file"
TAG_ATTRS = "attrs"

TAG_CACHED_COMMANDS = "cached commands"
TAG_DEBUG = "debug"
TAG_TOOLS = "tools"
TAG_FILTERS = "filters"
TAG_PATH = "path"

TAG_COVERAGE_LINES = "lines"
TAG_COVERAGE_FUNCS = "funcs"

TAG_SOURCE_DIR = "source dir"
TAG_SYSTEM_ID = "system"
TAG_CLADE_CONF = "clade config"
TAG_MAKE_COMMAND = "make command"
TAG_MAKE_CLEAN_COMMAND = "make clean command"
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
DEFAULT_INSTALL_DIR = "tools"
DEFAULT_COVERAGE_ARCH = "coverage.zip"
DEFAULT_COVERAGE_SOURCES_ARCH = "coverage_sources.zip"


COMMON_HEADER_FOR_RULES = "common.h"

DEFAULT_CIL_FILE = "cil.i"

TERMINATION_SUCCESS = "SUCCESS"
VERDICT_SAFE = "TRUE"
VERDICT_UNSAFE = "FALSE"
VERDICT_UNKNOWN = "UNKNOWN"

ENTRY_POINT_SUFFIX = "_caller"
STATIC_SUFFIX = "_static"

JSON_EXTENSION = ".json"
GRAPHML_EXTENSION = ".graphml"
ARCHIVE_EXTENSION = ".zip"

ERROR_TRACE_SOURCES = "error trace sources.json"

PREPARATOR_LOG_FILE = "log.txt"
TAG_LOG_FILE = "log"

TAG_METADATA = "metadata"
TAG_SUBSYSTEM = "subsystem"

CLADE_WORK_DIR = "clade-work-dir"
CLADE_BASE_FILE = "cmds.txt"

TAG_SOURCES = "sources"

DEFAULT_COVERAGE_SOURCE_FILES = "coverage.src"
