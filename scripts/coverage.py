#!/usr/bin/python3

import argparse
import logging
import multiprocessing
import os
import re
import subprocess
import sys
import zipfile
import shutil

from component import Component
from config import COMPONENT_COVERAGE, TAG_COVERAGE_LINES, TAG_COVERAGE_FUNCS, CLADE_WORK_DIR, DEFAULT_TOOL_PATH, \
    ET_LIB, TAG_TOOLS, COMMON_HEADER_FOR_RULES, DEFAULT_COVERAGE_ARCH, DEFAULT_INSTALL_DIR, TAG_DEBUG, \
    DEFAULT_COVERAGE_SOURCE_FILES

TAG_COVERAGE_MODE = "mode"
TAG_FULL_COVERAGE_MODE = "full mode"

COVERAGE_MODE_NONE = "none"  # Do not compute coverage.
COVERAGE_MODE_PERCENT = "percent"  # Present only percentage of coverage by lines/functions.
COVERAGE_MODE_FULL = "full"  # Present full coverage.
COVERAGE_MODES = [
    COVERAGE_MODE_NONE,
    COVERAGE_MODE_PERCENT,
    COVERAGE_MODE_FULL
]

DEFAULT_COVERAGE_MODE = COVERAGE_MODE_FULL
DEFAULT_COVERAGE_FILE = "coverage.json"
DEFAULT_COVERAGE_FILES = ["coverage.info", "subcoverage.info"]
DEFAULT_WORK_DIRECTORY = "coverage"
DIRECTORY_WITH_GENERATED_FILES = "generated"


class Coverage(Component):
    def __init__(self, launcher_component: Component = None, basic_config=None, install_dir=None, work_dir=None):
        if launcher_component:
            config = launcher_component.config
        else:
            config = basic_config
        super(Coverage, self).__init__(COMPONENT_COVERAGE, config)
        if launcher_component:
            self.install_dir = launcher_component.install_dir
            self.launcher_dir = launcher_component.work_dir
        else:
            self.install_dir = install_dir
            self.launcher_dir = work_dir
        self.mode = self.component_config.get(TAG_COVERAGE_MODE, DEFAULT_COVERAGE_MODE)
        self.full_mode = self.component_config.get(TAG_FULL_COVERAGE_MODE, "full")
        self.internal_logger = logging.getLogger(name=COMPONENT_COVERAGE)
        self.internal_logger.setLevel(self.logger.level)

    def compute_coverage(self, source_dirs: set, launch_directory: str, queue: multiprocessing.Queue = None):
        cov_lines, cov_funcs = 0.0, 0.0
        if self.mode == COVERAGE_MODE_NONE:
            return
        for file in DEFAULT_COVERAGE_FILES:
            if os.path.exists(os.path.join(launch_directory, file)):
                if file:
                    os.chdir(launch_directory)
                    try:
                        process_out = subprocess.check_output("genhtml {} --ignore-errors source".format(file),
                                                              shell=True, stderr=subprocess.STDOUT)
                        for line in process_out.splitlines():
                            line = line.decode("utf-8", errors="ignore")
                            res = re.search(r'lines......: (.+)% ', line)
                            if res:
                                cov_lines = float(res.group(1))
                            res = re.search(r'functions..: (.+)% ', line)
                            if res:
                                cov_funcs = float(res.group(1))
                        if self.mode == COVERAGE_MODE_FULL:
                            self.__full_coverage(source_dirs, os.path.abspath(file))
                        break
                    except Exception as e:
                        self.logger.warning(e, exc_info=True)
        os.chdir(self.launcher_dir)

        if queue:
            data = self.get_component_full_stats()
            data[TAG_COVERAGE_LINES] = cov_lines
            data[TAG_COVERAGE_FUNCS] = cov_funcs
            queue.put(data)

    def __full_coverage(self, source_dirs: set, coverage_file: str):
        dummy_dir = ""
        for src_dir in source_dirs:
            if os.path.exists(os.path.join(src_dir, CLADE_WORK_DIR)):
                dummy_dir = os.path.join(src_dir, CLADE_WORK_DIR)
                break

        # Export libs.
        et_parser_lib = self.get_tool_path(DEFAULT_TOOL_PATH[ET_LIB], self.config.get(TAG_TOOLS, {}).get(ET_LIB))
        sys.path.append(et_parser_lib)
        # noinspection PyUnresolvedReferences
        from core.coverage import LCOV

        lcov = LCOV(self.internal_logger, coverage_file, dummy_dir, source_dirs, [], self.launcher_dir, self.full_mode,
                    ignore_files={os.path.join(DIRECTORY_WITH_GENERATED_FILES, COMMON_HEADER_FOR_RULES)})

        archive = os.path.join(DEFAULT_COVERAGE_ARCH)
        files = [DEFAULT_COVERAGE_FILE] + list(lcov.arcnames.keys())
        with open(archive, mode='w+b', buffering=0) as f:
            with zipfile.ZipFile(f, mode='w', compression=zipfile.ZIP_DEFLATED) as zfp:
                with open(DEFAULT_COVERAGE_SOURCE_FILES, mode="w") as f_s:
                    for file in files:
                        arch_name = lcov.arcnames.get(file, os.path.basename(file))
                        if file == DEFAULT_COVERAGE_FILE:
                            zfp.write(file, arcname=arch_name)
                        else:
                            f_s.write("{};{}\n".format(file, arch_name))
                os.fsync(zfp.fp)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()

    parser.add_argument("--sources-dirs", "-s", dest='sources', nargs='+', help="directories with sources",
                        required=True)
    parser.add_argument("--launch-dir", "-l", dest="launch", help="directory, which contains launch results",
                        required=True)
    parser.add_argument('--debug', "-d", action='store_true')

    options = parser.parse_args()

    default_install_dir = os.path.abspath(DEFAULT_INSTALL_DIR)
    if not os.path.exists(default_install_dir):
        default_install_dir = os.path.abspath(os.path.join(os.pardir, DEFAULT_INSTALL_DIR))

    generated_config = {
        COMPONENT_COVERAGE: {
            TAG_COVERAGE_MODE: COVERAGE_MODE_FULL,
            TAG_DEBUG: options.debug,
        }
    }

    if not os.path.exists(DEFAULT_WORK_DIRECTORY):
        os.makedirs(DEFAULT_WORK_DIRECTORY)

    cov = Coverage(basic_config=generated_config, install_dir=default_install_dir,
                   work_dir=os.path.abspath(DEFAULT_WORK_DIRECTORY))
    cov.compute_coverage(options.sources, options.launch)

    shutil.copy(os.path.join(options.launch, DEFAULT_COVERAGE_ARCH), os.getcwd())

    cov.get_component_full_stats()
