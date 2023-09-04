# Continuous Verifier

`Continuous Verifier` or CV verifies a given software systems against specified properties.

`CV` takes the following information
* a system under analysis `system_id` (C language), which consist of
* s set of subsystems `subsystem_1`, ..., `subsystem_k`;
* a set of properties `prop_1`, ..., `prop_n`;
* and configurations

then decomposes a given system, creates verification tasks and solves them. Each verification task consist of:
* a set of source files that correspond to a given subsystem;
* generated entry point (`main` function);
* checked property (either in form of specification automata or configuration).

Created tasks are solved by software verification tool (for more information see [SVCOMP](https://sv-comp.sosy-lab.org)).

## Defining a plugin

In order to adjust `CV` for a given `system_id` a plugin is required, which contains required configuration files.
Default plugin structure:
- `entrypoints` - description of subsystems with their entrypoints (example `entrypoints/example.json`);
- `properties/properties.json` - description of checked properties (example in repository);
- `properties/automata` - specification automata for checked properties;
- `properties/models` - additional model C-files;
- `patches/sources` - patches for source code, which may be required for building;
- `patches/preparation/conf.json` - contains additional options for building (example in repository);
- `patches/tools/cpachecker` - patches for software verification tool;
- `configs` - configurations of CV launches (example `configs/example.json`);
- `docs` - may include additional documentation.

By default, s given system can be verified against memory safety property (`smg`).

Plugin should be placed as `plugin/system_id`. Example of a plugin directory:
```
-plugin/
-system_id/
--entrypoints/
---subsystem_1.json
...
---subsystem_k.json
--patches/
---sources/
----build.patch
---preparation/
----conf.json
--configs/
---config_1.json
---config_2.json
--docs/
---readme.md
--properties/
---properties.json
---models/
----property_1.c
...
----property_n.c
---automata/
----property_1.spc
...
----property_n.spc
```

In this case, we can decompose system `system_id` into `subsystem_1`, ..., `subsystem_k` and then verify each subsystem
against `property_1`, ..., `property_n`.

If a plugin is placed into specific directory `plugin_dir`, it can be installed with command:
```shell
make install-plugin PLUGIN_DIR=<plugin_dir> PLUGIN_ID=<system_id>
```
Plugin can be deleted with:
```shell
make delete-plugins
```

## Installation

### Control groups setting

In order to compute and limit resources (CPU time, CPU cores, memory usage) control groups are required.
Control groups can be enabled on Ubuntu (16.04 - 20.04) or Fedora 22 with:
```shell
./install_cgroups.sh
```

Warning: Ubuntu 22 does not support v1 control groups, which are required by [BenchExec](https://github.com/sosy-lab/benchexec) tool.
In order to partially enable control groups (without memory accounting) you need to add
`cgroup_enable=memory cgroup_memory=1 systemd.unified_cgroup_hierarchy=0`
to `/etc/default/grub` and then run `sudo update-grub`.

### Enabling swap accounting

You can check swap accounting with:
```shell
if ls /sys/fs/cgroup/memory/memory.memsw.limit_in_bytes || ls /sys/fs/cgroup/memory.memsw.limit_in_bytes ; then
    echo "Swap accounting is installed";
else
    echo "Swap accounting is not installed";
fi
```
If swap accounting is already installed, then you can skip this.
Otherwise, it can be enabled by:
- Add `swapaccount=1` to `GRUB_CMDLINE_LINUX_DEFAULT` value in `/etc/default/grub` file.
- Execute `sudo update-grub`.
- Reboot.

Alternatively you can disable swap:
```shell
sudo swapoff -a
```

## Configuration of a single verification launch

Example of `CV` configuration can be found in `configs/example.json`.
Use it as a template to verify `system_id`:
 - `Launcher: resource limits: CPU time` – CPU time limitation for a single software verification tool launch in seconds;
 - `Launcher: resource limits: memory size` – RAM limitation for a single software verification tool launch in GB;
 - `Launcher: resource limits: number of cores` – CPU cores limitation for a single software verification tool launch;
 - `entrypoints desc` – a set of subsystems description (e.g., `subsystem_1`, ..., `subsystem_k`);
 - `properties` – a set of properties (e.g., `property_1`, ..., `property_n`);
 - `system` – system identifier (e.g., `system_id`).

Note: the number of parallel software verifier launches is calculated in the following way:
```
N = min(<avaiable RAM>/<RAM limitation>, <avaiable cores>/<cores limitation>)
```

Each source code directory requires additional element in `Builder: sources`:
```json
{
  "id": "name",
  "source dir": "absolute path to source directory",
  "branch": "name of branch (optional)",
  "build patch": "patch, which is applied before building (optional)",
  "patches": ["list of patches, which are applied after build (optional)"],
  "repository": "repository type (git, svn or null - no repository)",
  "build config": {
    "make command": "make command"
  }
}
```

Single verification launch:
```shell
scripts/launcher.py --config <configuration files>
```
Result archive will be placed in `results/results_<configuration name>_<timestamp>.zip.`

## Continuous verification

A single verification launch may require a lot of time (several days for big systems).
Continuous verification checks only those parts of a system, which were changed, which allows to save a lot of resources.
It consists of 4 steps:
1. Create a call graph for a system.
2. Get a list of functions, which were changed in a given range of commits.
3. Determine, which parts of each subsystem may call any changed function.
4. Verify only changed subsystems with selected on the previous step entrypoints.

Let us consider, there are configurations `config_1.json`, ..., `config_m.json`, which were fully verified.
In order to set up continuous verification one need to create common config (see template `configs/auto.json`) and put there
`config_1.json`, ..., `config_m.json` and repository info.
After that it can be launched with:
```shell
./scripts/auto_check.py -c <common config>
```

## Visualization of results

Visualization of results requires a deployed [CVV web-interface](https://github.com/vmordan/cvv) according to its instructions
(its `<host>` and `<port>` should be known).

In order to upload results to web-interface, add the following in the configuration:
```json
  "uploader": {
    "upload results": true,
    "identifier": "<id of parent report (number from <host>:<port>/jobs/<number>)>",
    "parent id": "true",
    "server": "<host>:<port>",
    "user": "<web-intarface user>",
    "password": "<web-inrface password>",
    "name": "<name of new report>"
  }
```

`CV` will upload each new report during continuous verification in web-interface automatically.

## Simple example

There is a simple test example of `CV` usage:
* A system can be found in `docs/examples/sources/`. It can be built with `make`.
* Subsystem description is `entrypoints/it.json` (whole system with 2 entry points).
* Description of properties is `properties/properties.json` (we use only memory safety property `smg`).
* Launch configuration is `configs/it.json`.
`CV` can be launched by:
```shell
./scripts/launch.py -c configs/it.json
```
