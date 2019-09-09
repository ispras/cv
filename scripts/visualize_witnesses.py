#!/usr/bin/python3

import argparse

from components.mea import *


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--result-dir", dest="result_dir", help="directory for visualised witnesses",
                        required=True)
    parser.add_argument("-d", "--directory", help="directory with witnesses to be visualized")
    parser.add_argument("-w", "--witness", help="witness to be visualized")
    parser.add_argument("-s", "--source-dir", dest="source_dir", help="directory with source files", default=None)
    parser.add_argument('-u', "--unzip", help="unzip resulting archives", action='store_true')

    parser.add_argument("--conversion", help="conversion function (required for witnesses filtering)",
                        default=DEFAULT_CONVERSION_FUNCTION)
    parser.add_argument("--comparison", help="comparison function (required for witnesses filtering)",
                        default=DO_NOT_FILTER)
    parser.add_argument("--additional-model-functions", dest='mf', nargs='+',
                        help="additional model functions, separated by whitespace (required for witnesses filtering)")

    parser.add_argument('--debug', action='store_true')

    options = parser.parse_args()

    args = dict()
    if options.mf:
        args[TAG_ADDITIONAL_MODEL_FUNCTIONS] = options.mf

    config = {
        COMPONENT_MEA: {
            TAG_COMPARISON_FUNCTION: options.comparison,
            TAG_CONVERSION_FUNCTION: options.conversion,
            TAG_CONVERSION_FUNCTION_ARGUMENTS: args,
            TAG_DEBUG: options.debug,
            TAG_CLEAN: False,
            TAG_UNZIP: options.unzip
        }
    }

    witnesses_dir = options.directory
    witness = options.witness
    if (witnesses_dir and witness) or (not witnesses_dir and not witness):
        sys.exit("Sanity check failed: please specify either a directory with witnesses (-d) or a single witness (-w)")
    if witness:
        witnesses = [witness]
    else:
        witnesses = glob.glob(os.path.join(options.directory, "witness.*{}".format(GRAPHML_EXTENSION)))

    install_dir = os.path.abspath(DEFAULT_INSTALL_DIR)
    if not os.path.exists(install_dir):
        install_dir = os.path.abspath(os.path.join(os.pardir, DEFAULT_INSTALL_DIR))

    mea = MEA(config, witnesses, install_dir, result_dir=options.result_dir, is_standalone=True)
    mea.logger.info("Processing {} witnesses".format(len(witnesses)))

    source_dir = options.source_dir
    if source_dir:
        source_dir_rel = os.path.basename(source_dir)
        if os.path.exists(source_dir_rel):
            os.remove(source_dir_rel)
        os.symlink(source_dir, source_dir_rel)

    witnesses = mea.filter()
    mea.logger.info("Successfully processed {} witnesses".format(len(witnesses)))

    if source_dir:
        source_dir_rel = os.path.basename(source_dir)
        if os.path.exists(source_dir_rel):
            os.remove(source_dir_rel)
