# Contributing

## Branches and commits

Work on a focused branch named after the change (`feature/spatial-kriging`,
`fix/upload-part-hash`). Commit messages describe the scientific or technical
effect, not the files touched. A commit that changes scientific behaviour states
the assumption it makes and the expected change in the output.

## Before opening a pull request

```bash
make install
make lint
make typecheck
make test
make coverage
make contracts
make stubs
```

Every gate must pass. The coverage gate is 90% overall for the backend and 95%
for contracts, hashing, normalization, split generation, and compatibility.
MyPy runs in strict mode over `backend/src`. The frontend must pass ESLint,
TypeScript, Vitest, and the production build.

## Where code belongs

The layering is strict, and a change that crosses a boundary is a design
problem, not a convenience.

| Concern | Location |
|---|---|
| HTTP handling | `backend/src/trendsmapp/api/` |
| Application services | `backend/src/trendsmapp/services/` |
| Scientific computation | `backend/src/trendsmapp/{spatial,temporal,ml,ingestion,normalization,qc}/` |
| Meaning of the data | `backend/src/trendsmapp/domain/` |
| Persistence | `backend/src/trendsmapp/persistence/` |
| Bytes on disk | `backend/src/trendsmapp/storage/` |
| Presentation | `frontend/src/` |

Route handlers never contain scientific calculations. The frontend never
interpolates, normalizes, runs quality control, or fits a model. A public
`__init__.py` exports names and metadata only: it never opens a database,
registers routes, reads environment variables, or performs scientific work.

## Prohibited constructs

No production file may contain `pass` as an execution branch, `NotImplementedError`,
a TODO-only branch, dummy data, mock output, or a silent fallback. The
repository-level scan (`make stubs`) fails the build when it finds one.
Deferred features are omitted entirely rather than represented by empty files or
disabled controls.

## Scientific changes

A scientific change states:

- the mathematical method and its implementation library and version;
- the units and the coordinate reference system used for every distance;
- the treatment of missing, censored, and invalid values;
- the boundary behaviour;
- the validation strategy and the expected change in existing outputs.

The method description in the generated methods record must match the settings
that actually executed. Add a scientific regression test with a deterministic
fixture and a justified tolerance.

## Schema and contract changes

- Database changes require a new Alembic revision with an explicit upgrade and
  downgrade, and a migration test.
- Contract changes update `contracts/openapi.v1.json`, the schema version
  files, the contract examples, and `CHANGELOG.md` in the same pull request.
  A breaking change requires a new API major version; an additive field inside
  `/api/v1` is backward compatible.
- Stored artifact documents change through a pure migration function registered
  in the migration registry. A migration never performs I/O.

## Dataset changes

A dataset change updates its provenance, license, checksum, dimensions,
expected interpretation, and tests together. Unlicensed data is never committed.
Uploaded files, databases, credentials, generated reports, and object-store
data are ignored by Git.

## Documentation

Keep the documentation truthful. A method that is not implemented is not
described as available, and a capability list is generated from the code rather
than written by hand.

## Review

Changes to the scientific core, the contract layer, or the deployment
configuration require a second reviewer. Reviews are about correctness,
reproducibility, and honesty about limits.
