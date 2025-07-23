# Development Guide

This document describes third-party tools used in the Continuous Verification (CV) framework and provides an overview of CV components.

## Third-Party Tools

### CVV Web Interface
- **Repository:** [CVV](https://github.com/vmordan/cvv)
- Purpose: Visualization of Continuous Verification results.

### CPAchecker
- **Repository:** [CPAchecker](https://cpachecker.sosy-lab.org)
- Purpose: Main software verification backend.
- Required versions are listed in `cpa.config` in the format:
```
<mode>;<repository>;<branch>
```

### BenchExec
- **Repository:** [BenchExec](https://github.com/sosy-lab/benchexec.git)
- Purpose: Enforces resource limits (CPU time, memory, cores) for verification tools.
- **Note:** BenchExec does **not fully work on Ubuntu 22** due to cgroup v1 deprecation.

### CIL (C Intermediate Language)
- **Repository:** [Frama-C CIL](https://forge.ispras.ru/projects/astraver/repository/framac)
- Purpose: Simplifies and unifies C files into a single file.
- Default: An old version (`tools/cil.xz`) is included but no longer supported.
- Install a newer version:
```shell
make install-frama-c-cil DEPLOY_DIR=<CV_deploy_directory>
```

### Clade
- **Repository:** [Clade](https://github.com/17451k/clade)
- Purpose: Intercepts build commands and extracts compilation details.
- Installed as a Python package.
- **Required version:** `3.6`.

### CIF (C Instrumentation Framework)
- **Repository:** [CIF](https://github.com/ldv-klever/cif)
- Purpose: Generates call graphs for continuous verification.
- Installation options:
  - **Precompiled version for Linux (x86_64):**
    ```shell
    DEPLOY_DIR=<CV_deploy_directory> make install-cif-compiled
    ```
  - **Build from source** (requires `flex` and ~30 minutes):
    ```shell
    DEPLOY_DIR=<CV_deploy_directory> make install-cif
    ```

## CV Components

- **Builder** – Builds source code and extracts build commands.
- **Qualifier** – Detects changed parts of a system within a commit range.
- **Preparator** – Prepares verification tasks by unifying source code.
- **CPAchecker** – Verification backend for solving verification tasks.
- **MEA** – Filters duplicate error traces.
- **Exporter** – Generates the final verification report.
- **Launcher** – Orchestrates the entire verification process.
