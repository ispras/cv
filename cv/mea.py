#!/usr/bin/python3

"""
This script provides functionality to filter a given witnesses.
"""

import argparse
import glob
import os

from components import DefaultDir
from components.mea import TAG_CLEAN, TAG_DRY_RUN, TAG_SOURCE_DIR, TAG_UNZIP, TAG_CONVERSION_FUNCTION_ARGUMENTS, MEA
from mea.core import TAG_ADDITIONAL_MODEL_FUNCTIONS, TAG_COMPARISON_FUNCTION, TAG_CONVERSION_FUNCTION, \
    DEFAULT_COMPARISON_FUNCTION, DEFAULT_CONVERSION_FUNCTION
from models.tags import ComponentName, Tag, Extension


def _create_config(options=None, conversion_function="", comparison_function=""):
    additional_mf = []
    is_debug = False
    if options:
        conversion_function = options.conversion
        comparison_function = options.comparison
        additional_mf = options.mf or []
        is_debug = options.debug
    return {
        ComponentName.MEA: {
            TAG_COMPARISON_FUNCTION: comparison_function,
            TAG_CONVERSION_FUNCTION: conversion_function,
            TAG_CONVERSION_FUNCTION_ARGUMENTS: {
                TAG_ADDITIONAL_MODEL_FUNCTIONS: additional_mf
            },
            Tag.DEBUG: is_debug,
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

    witnesses = glob.glob(os.path.join(options.directory, f"witness.*{Extension.GRAPHML}"))
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
    install_dir = os.path.abspath(os.path.join(script_dir, DefaultDir.INSTALL))

    if not os.path.exists(install_dir):
        install_dir = os.path.abspath(os.path.join(os.pardir, DefaultDir.INSTALL))
    mea = MEA(config, witnesses, install_dir)
    mea.logger.debug(f"Received {len(witnesses)} witnesses")
    processed_witnesses = mea.filter()
    mea.logger.debug(f"Number of unique witnesses is {len(processed_witnesses)}")
    return processed_witnesses


if __name__ == "__main__":
    m_witnesses, m_config = _parse_cmdline()
    for witness in execute_filtering(m_witnesses, m_config):
        print(f"Unique witness '{witness}'")
