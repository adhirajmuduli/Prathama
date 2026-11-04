# Reproducibility

Reproducibility means that a published result can be regenerated from the
published inputs, with the published code, and that the regenerated result is
recognisably the same result. This document describes the mechanisms of the
rebuild, the state of each one, and the procedure a reader follows to repeat
an analysis.

## 1. Identities

| Object | Identity | State |
| --- | --- | --- |
| Raw upload | SHA-256 of the exact received bytes | Implemented (`hashing.py`, `storage/`) |
| Stored object | SHA-256 of the exact stored bytes, verified on write | Implemented |
| Dataset | SHA-256 of the canonical serialization | Implemented (`domain/provenance.py`) |
| Artifact | SHA-256 of the artifact bytes, unique per digest | Implemented (`persistence/repositories/artifacts.py`) |
| Dependency lock | SHA-256 of `backend/uv.lock` and `frontend/pnpm-lock.yaml` | Implemented (`scripts/hash_lockfiles.py`) |
| Contract snapshot | SHA-256 of `contracts/openapi.v1.json` | Implemented (`scripts/check_contract_compatibility.py`) |

The canonical serialization is deterministic: keys are sorted, the separator is
fixed, and the encoding is UTF-8 without a byte-order mark. Two runs that
produce the same data produce the same digest.

## 2. Versions in every result

Every result carries:

* `schema_version` — the version of the schema the result was written with;
* `application_version` — the build that wrote it;
* `run_id` — the identifier of the run that produced it.

A result without those three values is incomplete and is rejected when it is
registered.

## 3. Seeds

Every stochastic step of an analysis draws its seed from the run, never from
the global random state. The run records the seed of every step:

* the seed of the train and validation split;
* the seed of the model initialization;
* the seed of the bootstrap or permutation procedure.

A result that cannot state its seed is not reproducible and is not published.

## 4. Environment capture

The environment of a run is captured from the process that produced it:

* the application version and the build metadata (`TRENDSMAPP_BUILD_COMMIT`,
  `TRENDSMAPP_BUILD_TIMESTAMP`, `TRENDSMAPP_BUILD_BUILDER`);
* the digest of the dependency lock;
* the Python version and the interpreter implementation;
* the operating system and the machine architecture;
* the versions of the numerical libraries that determine a result.

The capture is part of the run metadata, not an optional extra. A run whose
environment cannot be captured is not a published run.

## 5. The reproducibility manifest

The manifest is the single document that ties a published result to everything
needed to repeat it. It contains:

* the dataset identity and the digests of its source files;
* the recipe, with its schema version and every parameter;
* the seeds and the split definition;
* the environment capture of section 4;
* the artifact list with the digest, the size, and the media type of each;
* the metrics and the uncertainty intervals of the run;
* the commands that reproduce the run.

The manifest is written by the export step of a run and is stored next to the
artifacts it describes. Its own digest is published with the results.

**Status:** the manifest schema and the export step are not implemented yet.
The identity mechanisms of section 1, the version fields of section 2, and the
run and artifact tables they belong to are implemented.

## 6. Procedure to repeat an analysis

1. Obtain the dataset version. Its digest is published with the result and
   must match the digest of the copy that is used.
2. Obtain the code version. The commit is part of the published metadata, and
   the dependency lock of that commit fixes the numerical libraries.
3. Apply the recipe. The recipe document is published with its schema
   version; a reader applies it unchanged.
4. Compare the manifest. The digests of the artifacts must match. A difference
   in a floating-point artifact is acceptable only when the difference is
   below the tolerance that the run recorded.
5. Report the difference. A reproduction that does not match is a result and
   is reported with the same rigour as the original.

## 7. What is verified in CI

* The dependency lock digests are recorded and current
  (`scripts/hash_lockfiles.py --check`).
* The contract snapshot digest is recorded in the compatibility note and
  current (`scripts/check_contract_compatibility.py`).
* The committed payload examples still match the running API
  (`scripts/verify_contract_examples.py`).
* No production path contains a placeholder branch
  (`scripts/check_no_stubs.py`).
