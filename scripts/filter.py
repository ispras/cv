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
This script provides functionality to filter a given witnesses.
"""

import argparse

from components.mea import *


def _create_config(options=None, conversion_function="", comparison_function=""):
    additional_mf = []
    is_debug = False
    if options:
        conversion_function = options.conversion
        comparison_function = options.comparison
        additional_mf = options.mf or []
        is_debug = options.debug
    return {
        COMPONENT_MEA: {
            TAG_COMPARISON_FUNCTION: comparison_function,
            TAG_CONVERSION_FUNCTION: conversion_function,
            TAG_CONVERSION_FUNCTION_ARGUMENTS: {
                TAG_ADDITIONAL_MODEL_FUNCTIONS: additional_mf
            },
            TAG_DEBUG: is_debug,
            TAG_CLEAN: False,
            TAG_UNZIP: False,
            TAG_DRY_RUN: False,
            TAG_SOURCE_DIR: None
        }
    }


def _parse_cmdline() -> tuple:
    parser = argparse.ArgumentParser()
    parser.add_argument("-d", "--directory", help="directory with witnesses to be filtered",
                        required=True)
    parser.add_argument("--conversion", help="conversion function",
                        default=DEFAULT_CONVERSION_FUNCTION)
    parser.add_argument("--comparison", help="comparison function",
                        default=DEFAULT_COMPARISON_FUNCTION)
    parser.add_argument("--additional-model-functions", dest='mf', nargs='+',
                        help="additional model functions, separated by whitespace")
    parser.add_argument('--debug', action='store_true')
    options = parser.parse_args()

    witnesses = glob.glob(os.path.join(options.directory, f"witness.*{GRAPHML_EXTENSION}"))
    return witnesses, _create_config(options)


def execute_filtering(witnesses: list, config=None, conversion_function="",
                      comparison_function="") -> list:
    """
    Filter the given violation witnesses.
    """
    if not config:
        config = _create_config(conversion_function=conversion_function,
                                comparison_function=comparison_function)
    script_dir = os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir)
    install_dir = os.path.abspath(os.path.join(script_dir, DEFAULT_INSTALL_DIR))

    if not os.path.exists(install_dir):
        install_dir = os.path.abspath(os.path.join(os.pardir, DEFAULT_INSTALL_DIR))
    mea = MEA(config, witnesses, install_dir)
    mea.logger.debug(f"Received {len(witnesses)} witnesses")
    processed_witnesses = mea.filter()
    mea.logger.debug(f"Number of unique witnesses is {len(processed_witnesses)}")
    return processed_witnesses


if __name__ == "__main__":
    m_witnesses, m_config = _parse_cmdline()
    for witness in execute_filtering(m_witnesses, m_config):
        print(f"Unique witness '{witness}'")
