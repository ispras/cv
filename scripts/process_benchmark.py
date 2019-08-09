#!/usr/bin/python3

import argparse

from components.benchmark_launcher import BenchmarkLauncher as Launcher, TAG_BENCHMARK_CLIENT_DIR, TAG_BENCHMARK_FILE, \
    TAG_TOOL_DIR, TAG_TASKS_DIR, TAG_OUTPUT_DIR, TAG_TOOL_NAME

if __name__ == '__main__':
    # Support the following modes:
    # 1. Launch specified benchmark, process results and upload them into the CV web-interface.
    # 2. Process results of benchmark and upload them into the CV web-interface.
    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", help="config file with options", required=True)
    parser.add_argument("-l", "--launch", help="launch benchmark", action='store_true')
    parser.add_argument("-o", "--output", help="benchmark output directory", default=None)
    parser.add_argument("-t", "--tasks", help="tasks directory", default=None)
    parser.add_argument("-b", "--benchmark-client", dest="client", help="benchmark client directory", default=None)
    parser.add_argument("-f", "--benchmark", help="benchmark xml file", default=None)
    parser.add_argument("-v", "--verifier", help="verifier directory", default=None)
    parser.add_argument("-n", "--name", help="tool name", default=None)
    options = parser.parse_args()

    additional_config = {
        TAG_OUTPUT_DIR: options.output,
        TAG_TASKS_DIR: options.tasks,
        TAG_BENCHMARK_CLIENT_DIR: options.client,
        TAG_BENCHMARK_FILE: options.benchmark,
        TAG_TOOL_DIR: options.verifier,
        TAG_TOOL_NAME: options.name
    }

    launcher = Launcher(options.config, additional_config)
    if options.launch:
        launcher.launch_benchmark()
    launcher.process_results()
