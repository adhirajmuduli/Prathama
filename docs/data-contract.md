# Data contract

This document defines the data that enters the system, the canonical form it
takes, and the rules that keep the form stable. It covers the parts that are
implemented today; the parts that are still planned are marked as such.

## 1. Canonical observation

Every ingested row becomes one observation record. The record keeps the
original value and everything needed to interpret it.

| Field | Meaning | State |
| --- | --- | --- |
| `observation_id` | Stable identifier of the observation | Implemented (`domain/identifiers.py`) |
| `dataset_id` | Dataset the observation belongs to | Implemented (`domain/models.py`) |
| `station_id` | Station the observation was measured at | Implemented |
| `parameter` | Measured quantity, for example `dissolved_oxygen` | Implemented |
| `value` | The value as it was measured | Implemented |
| `unit` | Unit of `value`, normalized through the unit registry | Implemented (`domain/units.py`) |
| `qualifier` | Quality qualifier attached by the source | Implemented |
| `observed_at` | Timestamp of the measurement, in UTC | Implemented |
| `source` | Origin of the record, with its licence | Implemented (`domain/provenance.py`) |
| `quality_flags` | Flags raised by quality control | Implemented (`domain/models.py`) |
| `ingested_at` | Time of ingestion | Implemented |

The rules:

* A raw value is never overwritten. A transformation adds a new observation and
  leaves the input intact.
* A unit is never guessed. A value without a unit, or with an unknown unit, is
  rejected at ingestion with a structured error.
* A timestamp without a timezone is rejected rather than assumed.
* A coordinate without an explicit role — longitude, latitude, easting,
  northing — is rejected. The role is chosen by the analyst, never inferred
  from the column order.

## 2. Units

Units are handled by a single registry (`domain/units.py`) built on `pint`.
The registry provides:

* a canonical name for a unit, for example `mg/L` instead of `1 milligram`;
* a dimensionality signature, for example `[mass]` or `dimensionless`, so that
  two quantities can be compared before they are combined;
* a parse that rejects an unknown unit instead of dropping the value.

A change of unit is a change of contract: a field never changes its unit
inside a major version.

## 3. Quality control

Quality control produces flags. It never deletes an observation.

| Flag | Meaning |
| --- | --- |
| `out_of_range` | The value is outside the accepted range of its parameter |
| `duplicate` | Another observation of the same station, parameter, and time exists |
| `invalid_timestamp` | The timestamp is not parseable or is outside the series |
| `missing_coordinate` | The observation has no usable position |
| `unit_mismatch` | The value does not match the expected dimensionality |
| `station_mismatch` | The station of the observation differs from the declared station |

A flagged observation is still stored, still exported, and still counted in the
quality report. The analysis decides how to treat a flag, and the decision is
recorded with the run.

## 4. Datasets, runs, and artifacts

* A **dataset** is an immutable set of observations with its provenance. Its
  identity is the SHA-256 digest of its canonical serialization.
* A **run** is one execution of a recipe against a dataset. It records the
  recipe, the recipe schema version, the application version, the seeds, and
  the parameters.
* An **artifact** is a stored output: a table, a raster, a figure, a video, or
  a report. Every artifact records its digest, its size, its media type, and
  the run that produced it.

Artifact references are unique by digest: storing the same bytes twice does
not create a second artifact.

## 5. Provenance

Every source of data carries:

* the origin, including the organization or the repository;
* the licence and the attribution that the licence requires;
* the retrieval date;
* the digest of the retrieved bytes.

The default boundary of the rebuild is only published when its source and
reuse rights are documented. The boundary used by the frozen prototype is
recorded in `docs/legacy-audit.md`; the rebuild has not published a default
boundary yet.

## 6. Versions

| Artifact | Version | Source of truth |
| --- | --- | --- |
| HTTP API | major version in the path | `contracts/versions.py` |
| Recipe document | `MAJOR.MINOR.PATCH` | `contracts/versions.py` |
| Manifest and result schema | `MAJOR.MINOR.PATCH` | `contracts/versions.py` |

The current values are exported to `contracts/schema-versions.json`. The
compatibility rules and the recorded changes are in `contracts/COMPATIBILITY.md`.

## 7. Planned parts

The following are part of the target design and are **not** implemented yet:
the ingestion parsers for the supported file formats, the mapping recipe that
describes the columns of an uploaded file, the interpolation result schema,
and the reproducibility manifest. They are listed here so that the intended
contract is known, and the implementation follows the contract rather than the
other way around.
