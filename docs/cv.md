# Continuous Verifier (CV)

`Continuous Verifier` (CV) is a framework for verifying software systems against specified properties.
It automates the decomposition of a system, creates verification tasks, and runs verification tools.

## Table of Contents

- [Overview](#overview)
    - [How it works](#how-it-works)
- [Plugin Definition](#plugin-definition)
    - [Default Plugin Structure](#default-plugin-structure)
    - [Key Components](#key-components)
    - [Default Verification](#default-verification)
    - [Plugin Installation](#plugin-installation)
- [Installation](#installation)
    - [Control Groups (cgroups) Setup](#control-groups-cgroups-setup)
        - [Ubuntu 22+](#ubuntu-22)
    - [Swap Accounting](#swap-accounting)
- [Configuration for a Single Verification Launch](#configuration-for-a-single-verification-launch)
    - [Source Code Configuration](#source-code-configuration)
    - [Run a Verification](#run-a-verification)
- [Continuous Verification](#continuous-verification)
- [Results Visualization](#results-visualization)
- [Simple Example](#simple-example)

## Overview

CV requires the following inputs:

- **System under analysis** (`system_id`) – a C-language system consisting of:
    - a set of subsystems (`subsystem_1`, …, `subsystem_k`)
- **Properties** to be verified (`prop_1`, …, `prop_n`)
- **Configurations** for the verification process

### How it works

1. Decomposes the system into subsystems.
2. Creates **verification tasks**, each consisting of:
    - Relevant source files for a subsystem
    - A generated entry point (`main` function)
    - The property to check (via specification automata or configuration)
3. Executes verification tasks using software verification tools ([SV-COMP tools](https://sv-comp.sosy-lab.org)).

## Plugin Definition

To verify a specific system (`system_id`), a **plugin** is required.
A plugin provides configuration and resources for CV to analyze the system.

### Default Plugin Structure

```
plugin/
└── system_id/
    ├── entrypoints/         # Subsystem entrypoint descriptions
    ├── patches/
    │   ├── sources/         # Source code patches (if needed)
    │   └── preparation/     # Additional build configuration
    ├── configs/             # Launch configurations
    ├── properties/
    │   ├── properties.json  # Property descriptions
    │   ├── models/          # Additional C models for properties
    │   └── automata/        # Specification automata
    └── docs/                # Optional documentation
```

### Key Components

- **entrypoints/** – JSON files describing subsystems and entrypoints
- **properties/**:
    - `properties.json` – list of properties to check
    - `automata/` – specification automata for properties
    - `models/` – additional model files (C source)
- **patches/**:
    - `sources/` – patches applied to system sources
    - `preparation/conf.json` – extra build options
    - `tools/cpachecker` – patches for verification tools
- **configs/** – CV run configurations
- **docs/** – documentation

### Default Verification

By default, CV can check the **memory safety property** (`smg`).

### Plugin Installation

Install a plugin:

```shell
make install-plugin PLUGIN_DIR=<plugin_dir> PLUGIN_ID=<system_id>
```

Remove all installed plugins:

```shell
make delete-plugins
```

## Installation

### Control Groups (cgroups) Setup

CV uses [BenchExec](https://github.com/sosy-lab/benchexec) to limit resources (CPU, memory, cores).
Enable cgroups on **Ubuntu 16.04–20.04** or **Fedora 22**:

```shell
./install_cgroups.sh
```

#### Ubuntu 22+

Ubuntu 22 uses cgroups v2 by default, but BenchExec requires **cgroups v1**.
To enable partial cgroups support (no memory accounting):

1. Add to `/etc/default/grub`:
   ```
   cgroup_enable=memory cgroup_memory=1 systemd.unified_cgroup_hierarchy=0
   ```
2. Update GRUB:
   ```shell
   sudo update-grub
   ```
3. Reboot.

---

### Swap Accounting

Check if swap accounting is enabled:

```shell
if ls /sys/fs/cgroup/memory/memory.memsw.limit_in_bytes || ls /sys/fs/cgroup/memory.memsw.limit_in_bytes; then
    echo "Swap accounting is installed";
else
    echo "Swap accounting is not installed";
fi
```

Enable swap accounting:

1. Add `swapaccount=1` to `GRUB_CMDLINE_LINUX_DEFAULT` in `/etc/default/grub`
2. Run:
   ```shell
   sudo update-grub
   sudo reboot
   ```

Alternatively, disable swap:

```shell
sudo swapoff -a
```

## Configuration for a Single Verification Launch

Example configuration: `configs/example.json`.
Key parameters:

- **Launcher: resource limits**
    - `CPU time` – in seconds
    - `Memory size` – in GB
    - `Number of cores` – CPU cores per verifier
- **entrypoints desc** – list of subsystems
- **properties** – list of properties
- **system** – system identifier

Parallel jobs calculation:

```
N = min(available_RAM / RAM_limit, available_cores / core_limit)
```

### Source Code Configuration

Each source directory requires:

```json
{
  "id": "name",
  "source dir": "absolute path",
  "branch": "optional branch",
  "build patch": "optional patch",
  "patches": [
    "list of patches"
  ],
  "repository": "git | svn | null",
  "build config": {
    "make command": "make"
  }
}
```

### Run a Verification

```shell
scripts/launcher.py --config <config files>
```

Results: `results/results_<config_name>_<timestamp>.zip`

---

## Continuous Verification

Large systems may take days to verify.
**Continuous verification** optimizes by verifying only changed parts.

Steps:

1. Build call graph
2. Identify changed functions between commits
3. Determine affected subsystems
4. Verify only relevant subsystems

Create a common config (template: `configs/auto.json`) referencing previous configs:

```shell
./scripts/auto_check.py -c <common config>
```

---

## Results Visualization

Requires [CVV web interface](https://github.com/vmordan/cvv).

Add to config:

```json
"uploader": {
    "upload results": true,
    "identifier": "<parent report ID>",
    "parent id": "true",
    "server": "<host>:<port>",
    "user": "<username>",
    "password": "<password>",
    "name": "<report name>"
}
```

CV will automatically upload results during continuous verification.

---

## Simple Example

Example files:

- Sources: `docs/examples/sources/` (build with `make`)
- Subsystem description: `entrypoints/it.json`
- Properties: `properties/properties.json` (includes `smg`)
- Config: `configs/it.json`

Run:

```shell
./scripts/launch.py -c configs/it.json
```
