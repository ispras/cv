# Klever Bridge

Klever Bridge is a component of the Continuous Verification framework that **exports results from the [Klever verification system](https://github.com/ldv-klever/klever)** into the CV format for visualization.

## Overview

Klever Bridge provides an interface between **Klever** and **CV** by transforming Klever verification results into a format suitable for CV visualization.

## Terminology

Key Klever concepts used in this integration:

- **Verification Task**
  A single task consists of:
  - A C file with a given entry point
  - A set of error locations
  - A configuration
  Klever generates tasks based on Linux kernel modules and properties (e.g., memory safety).

- **Verification Backend**
  A verification tool (e.g., CPAchecker) that processes the task and produces a result.

- **Verification Result**
  Can include:
  - **Correctness witness**: proof that an error location is unreachable from the entry point
  - **Violation witnesses**: paths from the entry point to error locations in the source code
  - **Failure reason**: why the verifier failed (optionally with violation witnesses)

- **Job**
  A set of solved verification tasks grouped by certain attributes.

- **Build Base**
  Source code of the Linux kernel prepared by the **Clade** tool.

## How Klever Bridge Works

Klever Bridge locates all solved verification tasks for a given **job**, converts them into CV format, and exports them for visualization.

## Installation

First, deploy the [CVV web interface](https://github.com/vmordan/cvv) following its documentation.

Install Klever Bridge in the CV deployment directory:
```shell
make install-klever-bridge DEPLOY_DIR=<path_to_deploy_directory>
```

## Usage

Create a configuration file `klever.json` in the `<deploy directory>`:
```json
{
  "Benchmark Launcher": {
    "tool": "CPAchecker",
    "job id": "<job_id>",
    "output dir": "<path_to_directory_with_Klever_solved_tasks>",
    "tasks dir": "<path_to_build_base>/Storage/"
  },
  "uploader": {
    "upload results": true,
    "parent id": true,
    "identifier": "<parent_report_identifier>",
    "server": "<host>:<port>",
    "user": "<username>",
    "password": "<password>",
    "name": "<new_report_name>"
  }
}
```

Run Klever Bridge:
```shell
./scripts/bridge.py -c klever.json
```

## Klever Runner

Klever Runner automates:
1. Building the **build base** for a Linux kernel
2. Launching Klever
3. Exporting results via Klever Bridge

Example configs are in `configs/bridge/`.

Run Klever Runner from the `<deploy directory>`:
```shell
sudo ./scripts/runner.py -c runner.json -d <path_to_Linux_kernel>
```

## Klever Configuration

To ensure proper visualization in CV, enable:
- `Keep intermediate files inside the working directory of Klever Core` in **Other settings** of the Klever job configuration.

For **correctness witness visualization** in CV, add these options:
```json
{"-setprop": "cpa.arg.proofWitness=witness.correctness.graphml"},
{"-setprop": "cpa.arg.export=true"},
{"-setprop": "cpa.arg.compressWitness=false"}
```
