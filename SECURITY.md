# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | yes |
| < 0.1 | no |

The rebuild is pre-release software. The scientific pipeline is not yet
complete, so this release must not be exposed to untrusted uploads on a public
address.

## Reporting a vulnerability

Report vulnerabilities privately to the repository owner. Do not open a public
issue for an unreported vulnerability, and do not include personal data,
credentials, or exploit details in a public report. Include the affected
component, the reproduction steps, and the impact you observed.

The disclosure timeline, the supported-versions table above, and the private
security contact must be completed with the real repository owner before the
first public release.

## Secret handling

- Secrets live in the deployment secret store. They never enter the repository,
  the container image, the client bundle, or the logs.
- `.env` files are ignored. `.env.example` is committed and contains no secret.
- The prototype's tracked `.secret` file is not an input to the rebuilt
  application; rotate any credential that was ever stored in it.
- Logs redact authorization headers, cookies, tokens, credentials, API keys, and
  private keys. Error envelopes never include stack traces, SQL text, connection
  strings, or file contents.

## Upload threat model

Uploaded files are untrusted input.

- Size ceilings are enforced in the browser, at the reverse proxy, in the API
  middleware, and again in the parser. A request above the ceiling is rejected,
  never silently reduced.
- Storage keys are derived from identifiers and digests. Client-supplied paths
  are rejected, including absolute paths, parent traversal, and empty segments.
- Content type is validated from the bytes, not from the declared header.
- Workbook limits cover sheet count, cell count, decompression ratio, and
  formula cells.
- Analysis is bounded by documented ceilings: grid cells per frame, timestamps
  per run, animation frames, candidate models, search trials per model, and
  explanation rows. Requests above a ceiling fail with a structured error.

## API security

- HTTPS is terminated at a trusted proxy; the API trusts only the configured
  hostnames.
- CORS origins are explicit and credentials are not allowed.
- Every response carries a correlation identifier, and every failure uses the
  stable error envelope.
- Request bodies are capped before they are parsed.
- SQL access is parameterized through SQLAlchemy.
- Artifact identifiers are opaque; no local path or object-store key is
  accepted from a client.
- Job creation is idempotent: repeating a key with the same request returns the
  original job, and repeating it with different content returns a conflict.

## Dependency response process

Dependabot opens grouped pull requests for Python, npm, GitHub Actions, and
Docker updates. A dependency update merges only when the full CI suite passes:
lint, strict type checks, unit and integration tests, the coverage gate, the
contract snapshot check, and the no-placeholder scan.

Container images are scanned with Trivy, and a software bill of materials is
produced for each release. A critical vulnerability in a runtime dependency
blocks the release until it is fixed or explicitly documented with a
compensating control.

## Secrets in the client bundle

The frontend build fails if a server-only variable is referenced from a client
component. Turnstile, Upstash, and Resend credentials are read only in the
Next.js server runtime.
