# Publication workflow

This document describes how a study is frozen, run, exported, and reproduced
with Trendsmapp. It is the procedure a reader of a published result follows,
and the procedure the authors follow before they publish.

The scientific pipelines are delivered in phases. The workflow below marks the
steps that the current build supports and the steps that follow with the
corresponding pipeline.

## 1. Freeze the dataset

1. Collect the source files. Each source records its origin, its licence, the
   attribution it requires, the retrieval date, and the digest of the bytes.
2. Freeze the dataset version. The identity of a dataset is the SHA-256 digest
   of its canonical serialization, so a frozen dataset is identified by that
   digest and not by a file name.
3. Record the quality report. Quality control produces flags, never deletions;
   the report states how many observations carry each flag and which of them
   the analysis used.
4. Publish the dataset identity with the study. The identity, not a download
   link, is the reference.

**Status:** the provenance records and the dataset identity are implemented
(`domain/provenance.py`, `hashing.py`). The ingestion parsers and the quality
report writer arrive with the ingestion pipeline.

## 2. Write the recipe

A recipe is the request document of the analysis. It states:

* the dataset identity it applies to;
* the parameter and the station selection;
* the spatial and temporal method, with every parameter;
* the split definition and the seed;
* the requested outputs.

The recipe has a schema version. A recipe written for an older minor version
is accepted and migrated one version at a time by a deterministic migration
function; the applied version is recorded in the run.

**Status:** the version registry and the migration registry are implemented
(`contracts/versions.py`, `contracts/migrations.py`). The recipe document
itself arrives with the analysis endpoints.

## 3. Run the analysis

1. Submit the recipe. The API validates it, stores it, and enqueues a job.
2. The worker claims the job with a row lock, so the job runs exactly once.
3. The worker records the progress of every stage and the terminal status.
4. Every output is written to the object store and registered with its digest.

A failed job records the error code, the message, and the details. A failed
job is never silently retried into a different result.

**Status:** the queue, the job lifecycle, the heartbeat, and the artifact
registration are implemented (`worker/`, `persistence/repositories/`). The
analysis handlers arrive with the corresponding pipelines.

## 4. Validate the result

Before anything is published:

* the validation metrics are computed with the stated split, and the split is
  stated next to the metric;
* the uncertainty interval is reported with the same split;
* the explainability output names the model and the features it explains;
* the rendered figure states the unit of the mapped quantity and distinguishes
  observed from interpolated values;
* a second execution of the same recipe with the same seed produces the same
  artifact digests.

The last point is the reproducibility check of the study itself, and it is not
optional.

## 5. Export the study bundle

The export bundle contains:

* the reproducibility manifest (section 6 of `docs/reproducibility.md`);
* the tables of the manuscript, as files with a stated unit;
* the figures, as publication-resolution images with their captions;
* the code version, the dependency lock digest, and the seeds;
* the dataset identity and the quality report.

The bundle is the unit of publication. A reader who receives the bundle can
repeat the analysis without asking the authors for a file.

**Status:** the artifact store and the digest machinery are implemented; the
export bundle and the manifest writer are not.

## 6. Reproduce the manuscript outputs

A reader repeats the work as follows:

1. Verify the dataset identity against the digest in the manifest.
2. Check out the commit named in the manifest and install from the dependency
   lock.
3. Apply the recipe unchanged.
4. Compare the artifact digests with the manifest. A difference in a
   floating-point artifact is acceptable only below the tolerance that the run
   recorded; any other difference is a finding.
5. Report the reproduction, whether it matches or not.

## 7. What a published result always contains

| Element | Source of truth |
| --- | --- |
| Dataset identity | SHA-256 of the canonical dataset serialization |
| Recipe and its schema version | The recipe document of the run |
| Seeds | The run record |
| Code version and dependency digest | The run metadata |
| Artifact digests | The artifact registry |
| Metrics, intervals, and the split | The result document |
| Manifest digest | The export step |

An element that is missing is a defect in the study, not a formatting detail.
