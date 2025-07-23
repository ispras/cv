# Multiple Error Analysis (MEA)

Multiple Error Analysis (**MEA**) is a component for **semi-automatic filtering of violation witnesses (error traces)**
to reduce manual effort during software verification result analysis.

## Overview

MEA helps identify and remove duplicate error traces that correspond to the **same bug**, reducing redundant manual
examination. It combines automatic filtering with optional manual adjustments.

## Definitions

- **Error Trace (Violation Witness)**
  A sequence of operations from an entry point to the property violation.

- **MEA Concept**
  MEA uses a combination of functions to determine equality of error traces:
    1. **Conversion**: `conversion(t)` removes non-essential elements from a trace.
    2. **Comparison**: `comparison(t1, t2)` defines how two converted traces are compared.
    3. **Manual Adjustment**: `manual(t)` allows a user to edit a trace (remove or add elements).

Two traces `t1` and `t2` are considered equal if:

```
comparison(manual(conversion(t1)), conversion(t2)) ≡ true
```

Correct function specification ensures accurate equality detection.

## Automatic Filtering

Automatic filtering processes a set of violation witnesses and returns only **unique traces**.

### Supported Conversion Functions

1. **Model Functions Call Tree (`model functions`)** *(default)*
   Uses model function markers or error descriptions from the verifier.
2. **Call Tree (`call tree`)**
   Keeps only function calls and returns (stricter than model functions).
3. **Conditions (`conditions`)**
   Retains only conditions in the trace.
4. **Error Descriptions (`error descriptions`)**
   Keeps only verifier error descriptions.
5. **Full Trace (`full`)**
   No conversion; keeps the complete trace.

### Supported Comparison Functions

1. **Full Equality (`equal`)** *(default)*
   All elements must match exactly.
2. **Inclusion (`include`)**
   One trace must be a subsequence of another.
3. **No Filtering (`skip`)**
   Considers all traces different.

For multi-threaded traces, MEA calculates the **Jaccard index** for thread similarity. Equality requires meeting the **
similarity threshold** (default: 100%).

## Deployment

Install MEA into the deployment directory:

```shell
make install-mea DEPLOY_DIR=<deployment_directory>
```

## Usage

Run the filtering script:

```shell
<deployment_directory>/scripts/filter.py -d <directory_with_violation_witnesses>
```

The script outputs only **unique violation witnesses**.

## Manual Filtering

For advanced analysis, use the [CVV web interface](https://github.com/vmordan/cvv):

- Users can manually edit traces (e.g., remove irrelevant calls).
- Assign a **mark** (conversion, comparison, similarity) to indicate trace equivalence.
- All related traces are then marked as duplicates and skipped in later reviews.
- Incorrect marks can be modified later.

This process reduces redundant bug reporting by grouping equivalent traces.
