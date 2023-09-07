# Klever bridge

This component allows to export results of [Klever verification system](https://github.com/ldv-klever/klever) into `CV` format for their visualization.

Here we use the following Klever terminology:
- `Verification task` is a C file with a given entry point a set of error locations and configuration.
Klever creates verification tasks based on a given Linux kernel module and checked properties (for example, memory safety).
- Verification backend (for example, CPAchecker) solves a given task and provides verification result.
- `Verification result` is:
  - a correctness witness (proof that error location cannot be reached from a given entry point) or
  - a set of violation witnesses (paths in source code from an entry point to an error location) or
  - a reason of incorrect verifier termination (may be along with violation witnesses).
- `Job` is a set of solved verification tasks, grouped by some attributes.
- `Build base` - source code of Linux kernel, which was prepared by Clade tool.

Klever bridge finds all solved verification tasks for a given job and export them for visualization.

## Installation of Klever bridge

[CVV web-interface](https://github.com/vmordan/cvv) should be deployed according to its instructions.

```shell
make install-klever-bridge DEPLOY_DIR=<path to deploy directory>
```

## Usage

Create a configuration file `klever.json` in `<deploy directory>` with the following content:

```json
{
  "Benchmark Launcher": {
    "tool": "CPAchecker",
    "job id": "<job id>",
    "output dir": "<path to directory with Klever solved tasks>",
    "tasks dir": "<path to directory with build base>/Storage/"
  },
  "uploader": {
    "upload results": true,
    "parent id": true,
    "identifier": "<parent report identifier>",
    "server": "<host>:<port>",
    "user": "<user name>",
    "password": "<user password>",
    "name": "<new report name>"
  }
}
```

Then launch the following command:

```shell
./scripts/bridge.py -c klever.json
```

## Klever config

In order to visualize error traces CPAchecker config must include the following:
```json
{"-setprop": "parser.readLineDirectives=true"}
```
Note, Klever will not visualise traces with such option.

Also Klever job configuration should specify `Keep intermediate files inside the working directory of Klever Core` inside
`Other settings` section in order to visualize generated files in the error trace.

If you need to visualise correctness witnesses in CV, the following options are required:
```json
{"-setprop": "cpa.arg.proofWitness=witness.correctness.graphml"},
{"-setprop": "cpa.arg.export=true"},
{"-setprop": "cpa.arg.compressWitness=false"}
```

If you need to add coverage, set flag `Collect total code coverage` in the Klever job config.
