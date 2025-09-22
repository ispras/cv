#!/usr/bin/python3

# Continuous Verification Framework - processing and managing verification results.
# Repository: https://github.com/ispras/cv
#
# Copyright © 2025 Vitalii Mordan, ISP RAS
#
# SPDX-License-Identifier: Apache-2.0

"""
This script provides connection to Klever jobs.
"""

import argparse

from components.benchmark_launcher import TAG_TASKS_DIR, TAG_OUTPUT_DIR
from klever_bridge.launcher import KleverLauncher, TAG_JOB_ID, KERNEL_DIR

if __name__ == '__main__':
    # Support the following modes:
    # 1. Process results of solved Klever job and upload them into the CV web-interface.
    # TODO: 2. Launch all tasks in prepared Klever job.
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", help="config file with options", required=True)
    parser.add_argument("-l", "--launch", help="launch benchmark", action='store_true')
    parser.add_argument("-o", "--output", help="benchmark output directory", default=None)
    parser.add_argument("-t", "--tasks", help="tasks directory", default=None)
    parser.add_argument("-j", "--job", help="job id", default=None)
    parser.add_argument("-k", "--kernel-dir", dest="kernel_dir", help="directory with kernel dir")
    options = parser.parse_args()

    additional_config = {
        TAG_OUTPUT_DIR: options.output,
        TAG_TASKS_DIR: options.tasks,
        TAG_JOB_ID: options.job,
        KERNEL_DIR: options.kernel_dir
    }

    launcher = KleverLauncher(options.config, additional_config, options.launch)
    if options.launch:
        launcher.launch_benchmark()
    launcher.process_results()
