#!/usr/bin/python3
#
# CV is a framework for continuous verification.
#
# Copyright (c) 2018-2023 ISP RAS (http://www.ispras.ru)
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
This script provides connection to Klever jobs.
"""

import argparse

from components.benchmark_launcher import TAG_TASKS_DIR, TAG_OUTPUT_DIR
from klever_bridge.launcher import KleverLauncher, TAG_JOB_ID

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
    options = parser.parse_args()

    additional_config = {
        TAG_OUTPUT_DIR: options.output,
        TAG_TASKS_DIR: options.tasks,
        TAG_JOB_ID: options.job
    }

    launcher = KleverLauncher(options.config, additional_config, options.launch)
    if options.launch:
        launcher.launch_benchmark()
    launcher.process_results()
