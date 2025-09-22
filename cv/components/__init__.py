"""
Here global names are defined.
"""
from enum import Enum

BUSY_WAITING_INTERVAL = 1

LOG_FILE = "log.txt"


class DefaultDir(str, Enum):
    """
    Default directories.
    """
    WORK = "work_dir"
    RESULTS = "results"
    INSTALL = "tools"
    CLADE = "clade"
    EXPORT = "export"


class CoverageInfo(str, Enum):
    """
    Constants related to the coverage.
    """
    COVERAGE_MERGE_TYPE_UNION = "union"
    COVERAGE_MERGE_TYPE_INTERSECTION = "intersection"
    DEFAULT_COVERAGE_ARCH = "coverage.zip"
    DEFAULT_COVERAGE_SOURCES_ARCH = "coverage_sources.zip"
    DEFAULT_COVERAGE_FILE = "coverage.json"
    DEFAULT_COVERAGE_SOURCE_FILES = "coverage.src"


class CloudInfo(str, Enum):
    """
    Constants related to the cloud config.
    """
    SCHEDULER_CLOUD = "cloud"
    SCHEDULER_LOCAL = "local"
    DEFAULT_CLOUD_PRIORITY = "LOW"
    CLOUD_BENCHMARK_LOG = "benchmark_log.txt"


ERROR_TRACE_SOURCES = "error trace sources.json"

DEFAULT_VERIFIER_TOOL = "CPAchecker"
