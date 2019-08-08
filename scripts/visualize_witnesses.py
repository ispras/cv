#!/usr/bin/python3

from components.mea import *


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--conversion", help="conversion function", required=False, default=DEFAULT_CONVERSION_FUNCTION)
    parser.add_argument("--comparison", help="comparison function", required=False, default=DO_NOT_FILTER)
    parser.add_argument("--additional-model-functions", dest='mf', nargs='+',
                        help="add model functions, separated by whitespace", required=False)
    parser.add_argument("--directory", "-d", help="directory with error traces", required=True)
    parser.add_argument("--rule", "-r", help="rule specification, which is violated by traces", default="")
    parser.add_argument("--result-dir", dest="result_dir",
                        help="directory for saving processed html error traces", default="")
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
            TAG_CLEAN: False
        }
    }

    traces = glob.glob(os.path.join(options.directory, "witness.*{}".format(GRAPHML_EXTENSION)))

    install_dir = os.path.abspath(DEFAULT_INSTALL_DIR)
    if not os.path.exists(install_dir):
        install_dir = os.path.abspath(os.path.join(os.pardir, DEFAULT_INSTALL_DIR))

    mea = MEA(config, traces, install_dir, options.rule, options.result_dir)
    mea.clear()

    traces = mea.filter()
    mea.logger.info("Filtered traces:")
    for filtered_trace in traces:
        mea.logger.info(filtered_trace)
