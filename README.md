# Continuous Verification Framework

[![Apache 2.0 License](https://img.shields.io/badge/license-Apache--2-brightgreen.svg)](https://www.apache.org/licenses/LICENSE-2.0)
![Deploy Workflow](https://github.com/ispras/cv/actions/workflows/deploy.yml/badge.svg)
![Pylint Workflow](https://github.com/ispras/cv/actions/workflows/pylint.yml/badge.svg)

This framework enables **continuous verification** of generic software systems. It consists of the following tools:

- **Continuous Verifier (CV)**
  Verifies a target software system. To support a specific system, a plugin must define:
    - how to decompose the system (currently supports only C programs);
    - how to construct an environment model;
    - which properties to verify.

  📖 [CV Documentation](docs/cv.md)

- **Klever Bridge**
  Integrates with the [Klever framework](https://github.com/ldv-klever/klever) to verify Linux kernel modules.
  📖 [Klever Bridge Documentation](docs/klever_bridge.md)

- **Benchmark Visualizer**
  Processes and visualizes verification benchmarks from [SV-COMP](https://sv-comp.sosy-lab.org).
  📖 [Benchmark Visualizer Documentation](docs/benchmark_visualizer.md)

- **Witness Visualizer**
  Converts SV-COMP witnesses (error traces or proofs) into human-readable format.
  📖 [Witness Visualizer Documentation](docs/witness_visualizer.md)

- **Multiple Error Analyser (MEA)**
  Filters multiple witnesses to report only unique potential bugs.
  📖 [MEA Documentation](docs/mea.md)

📊 All verification results can be viewed using
the [Continuous Verification Visualizer (CVV)](https://github.com/vmordan/cvv).

## Requirements

Tested on **Ubuntu 20.04 and above**.

### Ubuntu Packages

Install required packages using:

```bash
sudo apt update
sudo apt install -y \
  git openjdk-17-jdk python3 python3-dev python3-pip ant lcov cmake
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
