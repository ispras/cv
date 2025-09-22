"""
Here is a structure of config files tags.
"""

from enum import Enum


class Tag(str, Enum):
    """
    Description of configuration tags.
    """
    DEBUG = "debug"
    OPTIMIZE = "optimize"
    METADATA = "metadata"
    SUBSYSTEM = "subsystem"
    ENTRYPOINTS = "entrypoints"
    LOG_FILE = "log"
    ADD_VERIFIER_PROOFS = "add verifier proofs"
    DIRS = "dirs"
    DIRS_WORK = "work"
    DIRS_RESULTS = "results"
    TOOLS = "tools"
    DEFAULT_TOOL_PATH = "default tool path"
    LIMIT_MEMORY = "memory size"
    LIMIT_CPU_TIME = "CPU time"
    LIMIT_CPU_CORES = "number of cores"
    CACHED = "cached"
    BRANCH = "branch"
    PATCH = "patches"
    BUILD_PATCH = "build patch"
    MAX_COVERAGE = "max"
    CALLERS = "callers"
    COMMITS = "commits"
    BACKUP_WRITE = "backup write"
    BACKUP_READ = "backup read"
    PARALLEL_LAUNCHES = "parallel launches"
    RESOURCE_LIMITATIONS = "resource limits"
    PROCESSES = "processes"
    SCHEDULER = "scheduler"
    CLOUD = "cloud"
    CLOUD_MASTER = "master"
    CLOUD_PRIORITY = "priority"
    UPLOADER_UPLOAD_RESULTS = "upload results"
    UPLOADER_IDENTIFIER = "identifier"
    UPLOADER_SERVER = "server"
    UPLOADER_USER = "user"
    UPLOADER_PASSWORD = "password"
    UPLOADER_PARENT_ID = "parent id"
    UPLOADER_REQUEST_SLEEP = "request sleep"
    SKIP = "skip"
    STATISTICS_TIME = "statistics time"
    BUILD_CONFIG = "build config"
    ID = "id"
    REPOSITORY = "repository"
    NAME = "name"
    VERIFIER_OPTIONS = "verifier options"
    EXPORT_HTML_ERROR_TRACES = "standalone error traces"
    EXITCODE = "exit code"
    CIL_FILE = "cil file"
    PREP_RESULTS = "prep results"
    ATTRS = "attrs"
    SOURCE_DIR = "source dir"
    FILTERS = "filters"
    PATH = "path"
    COVERAGE_LINES = "lines"
    COVERAGE_FUNCS = "funcs"
    FUNCTION_COVERAGE = "function coverage"
    LINE_COVERAGE = "line coverage"
    STATISTICS = "statistics"
    SOURCES = "sources"
    BENCHMARK_ARGS = "benchmark args"
    BENCHEXEC_OPTIONS = "benchexec options"
    COVERAGE = "coverage"
    FUNCTIONS_STATISTICS = "functions statistics"
    VALUES = "values"
    VERSION = "version"
    ADD_VERIFIER_LOGS = "add verifier logs"
    SOURCE_FILES = "source files"
    CONFIG_MEMORY_LIMIT = "Memory limit"
    CONFIG_CPU_TIME_LIMIT = "CPU time limit"
    CONFIG_CPU_CORES_LIMIT = "CPU cores limit"
    CONFIG_OPTIONS = "Options"


class ComponentName(str, Enum):
    """
    Names of CV components.
    """
    MAIN_GENERATOR = "Generator"
    PREPARATOR = "Preparator"
    LAUNCHER = "Launcher"
    BENCHMARK_LAUNCHER = "Benchmark Launcher"
    EXPORTER = "Exporter"
    MEA = "MEA"
    QUALIFIER = "Qualifier"
    BUILDER = "Builder"
    COVERAGE = "Coverage"


class Extension(str, Enum):
    """
    Supported extensions of intermediate files.
    """
    JSON = ".json"
    GRAPHML = ".graphml"
    ARCHIVE = ".zip"


class WitnessType(str, Enum):
    """
    Witness type.
    """
    VIOLATION = 'violation'
    CORRECTNESS = 'correctness'


class Resource(str, Enum):
    """
    Names of main resources.
    """
    CPU_TIME = "cpu"
    WALL_TIME = "wall"
    MEMORY_USAGE = "memory"
