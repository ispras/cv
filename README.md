# Continuous Verification Framework

[![Apache 2.0 License](https://img.shields.io/badge/license-Apache--2-brightgreen.svg)](https://www.apache.org/licenses/LICENSE-2.0)

This framework aims at applying continuous verification to generic software systems.
The framework consist of the following tools:
- `Continuous Verifier` (CV) verifies a given software systems. In order to support generic 
software system, a specific plugin is required, which shows
  - how to decompose a system (currently, only C language is supported);
  - how to create an environment for the system;
  - what properties should be verified in the system.

  [CV documentation](docs/cv.md).
- `Klever Bridge` allows to verify Linux kernel modules with help of [Klever framework](https://github.com/ldv-klever/klever).
[Klever Bridge documentation](docs/klever_bridge.md).
- `Benchmark Visualizer` allows to process and visualise verification benchmarks from [SV-COMP](https://sv-comp.sosy-lab.org).
[Benchmark Visualizer documentation](docs/benchmark_visualizer.md).
- `Witness Visualizer` converts generic witnesses (potential bug or proof) from [SV-COMP](https://sv-comp.sosy-lab.org) tools into user-friendly format.
[Witness Visualizer documentation](docs/witness_visualizer.md).
- `Multiple Error Analyser` (MEA) filters several witnesses in order to present only those, which corresponds to unique potential bugs.
[Witness Visualizer documentation](docs/mea.md).

All produced verification results can be visualised with help of [Continuous Verification Visualizer](https://github.com/vmordan/cvv).

## Requirements

The framework works with Ubuntu 18 and above.
All requirements can be installed with command:

```shell
sudo apt install git openjdk-11-jdk python3 python3-dev ant lcov cmake libmpc-dev lib32z1 libxslt-dev libpq-dev python3-pip
```

Additional python modules:

```shell
sudo pip3 install requests ujson graphviz ply pytest atomicwrites pathlib2 more-itertools pluggy py attrs setuptools six django clade==3.6 psycopg2 pyyaml pycparser sympy
```

## Installation

The framework is installed with the following command:
```
make install -j DEPLOY_DIR=<working dir>
```
