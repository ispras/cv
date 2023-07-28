Klever bridge
=============

This component allows to export results of Klever verification system into CV format for their visualization.

Here we use the following Klever terminology:
- `Verification task` is a C file with a given entry point a set of error locations and configuration. Klever creates verification tasks based on a given Linux kernel module and checked properties (for example, memory safety). Verification backend (for example, CPAchecker) solves a given task and provides verification result.
- `Verification result` is:
  - a correctness witness (proof that error location cannot be reached from a given entry point) or
  - a set of violation witnesses (paths in source code from an entry point to an error location) or
  - a reason of incorrect verifier termination (may be along with violation witnesses).
- `Job` is a set of solved verification tasks, grouped by some attributes.
- `Build base` - source code of Linux kernel, which was prepared by Clade tool.

Klever bridge finds all solved verification tasks for a given job and export them for visualization.

Installation of Klever bridge
-----------------------------

```shell
make install-klever-bridge DEPLOY_DIR=<path to deploy directory>
```

Usage
-----

Create a configuration file in `<deploy directory>` with the following content:

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
./scripts/bridge.py -c bv.json
```
