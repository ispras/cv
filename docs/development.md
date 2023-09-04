# Development

## Description of third party tools

1. [CVV web-interface](https://github.com/vmordan/cvv) continuous verification visualizer.
2. [Software verifier CPAchecker](https://cpachecker.sosy-lab.org) is a verification backend.
Required versions of the tool are placed in the `cpa.config` in the following format:
```
`<mode>;<repository>;<branch>`
```
3. [BenchExec](https://github.com/sosy-lab/benchexec.git) limits resource usage for verifier tool.
Note: does not work with Ubuntu 22.
4. [CIL](https://forge.ispras.ru/projects/astraver/repository/framac) simplifies C files and unifies them in a single file.
By default, an old version is used (`tools/cil.xz`), which is not supported anymore.
Alternatively you can use new version:
```shell
make install-frama-c-cil DEPLOY_DIR=<CV deploy directory>
```
5. [Clade](https://github.com/17451k/clade) is a tool for intercepting build commands. It is required for building.
Installed as a python package.
Note, version `3.6` is required.
6. [CIF](https://github.com/ldv-klever/cif) is required for call graph creation.
You can use either a compiled for `linux-x86_64` version:
```shell
DEPLOY_DIR=<CV deploy directory> make install-cif-compiled
```
or build the latest version (requires `flex` package and about 30 minutes):
```shell
DEPLOY_DIR=<CV deploy directory> make install-cif
```

## CV components

 - `Builder` – builds the source code and extracts build commands.
 - `Qualifier` – determines, which parts of a system was changed in the given commit range.
 - `Preparator` – prepares verification task by unifying source code.
 - `CPAchecker` – verification backend, which solves verification tasks.
 - `MEA` – filters error traces.
 - `Exporter` – prepares final report.
 - `Launcher` – main component.
