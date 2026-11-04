# Bundled validation dataset

`chilika_demo.xlsx` is the zero-configuration validation workbook loaded when
`TRENDSMAPP_DEMO_MODE=true` (the default). It contains 33 coordinate pairs and
12 monthly columns, normalizing to 395 non-blank observations.

| Field | Value |
|---|---|
| File | `chilika_demo.xlsx` |
| Format | XLSX, wide observation table |
| Spatial rows | 33 |
| Time columns | 12 (January-December 2024) |
| Normalized observations | 395 |
| SHA-256 | `ebfa146ad0040b41d3bb5713dba96956c6ce788eb71adf8e57b1a2357d0d7030` |

## Provenance status

The current repository does not contain an authoritative source URL, creator,
collection protocol, analyte name/unit, or data-specific reuse license for this
workbook. Therefore it is suitable for software validation but **must not be
described as a real-world open dataset in a manuscript yet**.

Before submission, the authors must either:

1. add the original citation, permanent repository DOI/URL, collection method,
   variable/unit definition, transformations, and reuse license; or
2. explicitly label the workbook as synthetic, replace its values with a
   reproducibly generated dataset, and document the generator and random seed.

Run `python scripts/verify_example.py` after any replacement. Update its locked
checksum and expected dimensions only as part of a reviewed dataset change.
