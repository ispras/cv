#!/usr/bin/python3

"""
This script provides functionality to visualize a given witness or a group of witnesses.
"""

import argparse
import glob
import os
import sys

from aux.common import clear_symlink, update_symlink
from components import DefaultDir
from components.mea import MEA, TAG_CONVERSION_FUNCTION_ARGUMENTS, TAG_CLEAN, TAG_UNZIP, TAG_DRY_RUN, TAG_SOURCE_DIR, \
    DO_NOT_FILTER
from mea.core import TAG_ADDITIONAL_MODEL_FUNCTIONS, TAG_COMPARISON_FUNCTION, TAG_CONVERSION_FUNCTION, \
    DEFAULT_CONVERSION_FUNCTION
from models.tags import ComponentName, Tag, Extension

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--result-dir", dest="result_dir",
                        help="directory for visualised witnesses", required=True)
    parser.add_argument("-d", "--directory", help="directory with witnesses to be visualized")
    parser.add_argument("-w", "--witness", help="witness to be visualized")
    parser.add_argument("-s", "--source-dir", dest="source_dir", help="directory with source files",
                        default=None)
    parser.add_argument('-u', "--unzip", help="unzip resulting archives", action='store_true')
    parser.add_argument("--dry-run", dest="dry_run",
                        help="do not visualize witnesses, only check their quality",
                        action='store_true')

    parser.add_argument("--conversion",
                        help="conversion function (required for witnesses filtering)",
                        default=DEFAULT_CONVERSION_FUNCTION)
    parser.add_argument("--comparison",
                        help="comparison function (required for witnesses filtering)",
                        default=DO_NOT_FILTER)
    parser.add_argument("--additional-model-functions", dest='mf', nargs='+',
                        help="additional model functions, separated by whitespace "
                             "(required for witnesses filtering)")

    parser.add_argument('--debug', action='store_true')

    options = parser.parse_args()

    args = {}
    if options.mf:
        args[TAG_ADDITIONAL_MODEL_FUNCTIONS] = options.mf

    config = {
        ComponentName.MEA: {
            TAG_COMPARISON_FUNCTION: options.comparison,
            TAG_CONVERSION_FUNCTION: options.conversion,
            TAG_CONVERSION_FUNCTION_ARGUMENTS: args,
            Tag.DEBUG: options.debug,
            TAG_CLEAN: False,
            TAG_UNZIP: options.unzip,
            TAG_DRY_RUN: options.dry_run,
            TAG_SOURCE_DIR: options.source_dir
        }
    }

    witnesses_dir = options.directory
    witness = options.witness
    if (witnesses_dir and witness) or (not witnesses_dir and not witness):
        sys.exit("Sanity check failed: "
                 "please specify either a directory with witnesses (-d) or a single witness (-w)")
    if witness:
        witnesses = [witness]
    else:
        witnesses = glob.glob(os.path.join(options.directory, f"witness.*{Extension.GRAPHML}"))

    install_dir = os.path.abspath(DefaultDir.INSTALL)
    if not os.path.exists(install_dir):
        install_dir = os.path.abspath(os.path.join(os.pardir, DefaultDir.INSTALL))

    mea = MEA(config, witnesses, install_dir, result_dir=options.result_dir, is_standalone=True)
    mea.logger.info(f"Processing {len(witnesses)} witnesses")

    source_dir = options.source_dir
    if source_dir:
        source_dir = os.path.normpath(os.path.abspath(options.source_dir.rstrip("/")))
        update_symlink(source_dir)

    witnesses = mea.filter()
    if not options.dry_run:
        mea.logger.info(f"Successfully processed {len(witnesses)} witnesses")

    clear_symlink(source_dir)
