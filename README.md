# Continuous Verification Framework

[![Apache 2.0 License](https://img.shields.io/badge/license-Apache--2-brightgreen.svg)](https://www.apache.org/licenses/LICENSE-2.0)
![Deploy Workflow](https://github.com/ispras/cv/actions/workflows/deploy.yml/badge.svg)
![Pylint Workflow](https://github.com/ispras/cv/actions/workflows/pylint.yml/badge.svg)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.16032807.svg)](https://doi.org/10.5281/zenodo.16032807)

# **Continuous Verification Framework (CVF)**

**Continuous Verification Framework (CVF)** is an integrated environment for analyzing, visualizing, and managing software verification results.
It builds on the [SV-COMP](https://sv-comp.sosy-lab.org) standards and extends them with a set of complementary tools to improve verification usability, trace inspection, and regression analysis.

## Key Components

* **Witness Visualizer** – converts SV-COMP witnesses (error traces or proofs) into a human-readable format. [📖 Documentation](docs/witness_visualizer.md)
* **Benchmark Visualizer** – processes and visualizes complete verification benchmarks. [📖 Documentation](docs/benchmark_visualizer.md)
* **Multiple Error Analyser (MEA)** – filters multiple witnesses to report only unique potential bugs. [📖 Documentation](docs/mea.md)
* **Klever Bridge** – integrates with the [Klever framework](https://github.com/ldv-klever/klever) to visualize Linux kernel module verification tasks. [📖 Documentation](docs/klever_bridge.md)

📊 Verification results can be explored through the web interface [Continuous Verification Visualizer (CVV)](https://github.com/vmordan/cvv).

## Requirements

Tested on **Ubuntu 20.04 and above**.

### Ubuntu Packages

Install required packages using:

```bash
sudo apt update
sudo apt install -y \
  git python3 python3-dev python3-pip lcov
```

### Python Dependencies

Install Python modules with:

```bash
pip3 install -r requirements.txt
```

## Installation

Run the following command to install the framework:

```bash
make install -j DEPLOY_DIR=<working_directory>
```

Replace `<working_directory>` with your preferred deployment path.
