# Multiple Error Analysis

## Definitions

An `error trace` (or violation witness) is a sequence of operations from an entry point to the property violation.

`Multiple Error Analysis` (MEA) stands for semi-automatic violation witnesses filtering.
The main goal of MEA is to exclude error traces, which corresponds to the same bug, from manual examination.
MEA defines equal error traces in the following way:
1) Conversion function `conversion(t)` removes none-essential elements from an error trace.
2) Comparison function `comparison(t1, t2)` defines, how elements of 2 error traces are compared.
3) Manual error trace editing `manual(t)` is performed by an user. It may remove or add any element.
Thus error trace `t2` is equal to error trace `t1`, which is analysed by an user, if:
```
comparison(manual(conversion(t1)), conversion(t2)) ≡ true
```
Note, that the traces are equal (e.g., correspond to the same bug) if corresponding functions are correctly specified.

## Automatic filtration

Automatic filtration takes a set of error traces and outputs only unique traces.

Supported conversion functions:
1) Model functions call tree (`model functions`). Is used by default.
Model functions are either marked in comments (Klever/LDV format) or contains special error description from software verifier in error trace.
2) Call tree (`call tree`) leaves only function calls and returns. It is more strict than `model_functions`.
3) Conditions (`conditions`) leaves only conditions in error trace.
4) Error description (`error descriptions`) leaves only special error descriptions from software verifier.
5) No conversion (`full`) returns full error trace.

Supported comparison functions:
1) Full equality (`equal`). Each element of converted error traces should be equal. Is used by default.
2) Comparison (`include`). One error trace should be inside another.
3) No filtering (`skip`). All traces are considered as different.

If an error trace includes several threads, then comparison function return Jaccard index for their equal thread, and
we consider them equal if it is more, than a given similarity threshold. By default similarity threshold is 100%.

### Deployment
MEA library can be installed in the `<deployment directory>` with the following command:
```shell
make install-mea DEPLOY_DIR=<deployment directory>
```

### Usage
```shell
<deployment directory>/scripts/filter.py -d <directory with violation witnesses>
```
All unique violation witnesses will be printed as a result.

## Manual filtering

[CVV web-interface](https://github.com/vmordan/cvv) can be used to perform manual filtering.
If there are several error traces, which correspond to the same bug, were uploaded after manual filtering,
the user needs to analyse them all (e.g., to create a bug report). In order to avoid analysing of the same traces,
manual filtering is performed. In this case the user crates a mark (`conversion`, `comparison`, `similarity`) and manually edits
the trace if needed (e.g., some function call does not relate to the bug). After that, `CVV` mark all other traces
as equal, and the user may skip their analysis. If mark was created incorrect
(e.g., the user then finds another similar trace, which was not marked), it can be edited.
