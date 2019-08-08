#!/usr/bin/python3

import argparse

from components.launcher import Launcher

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", help="list of config files", nargs="+", required=True)
    options = parser.parse_args()
    for config in options.config:
        launcher = Launcher(config)
        launcher.launch()
        del launcher
