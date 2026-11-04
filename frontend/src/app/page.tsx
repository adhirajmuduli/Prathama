import { ApiStatusPanel } from "../components/api-status-panel";
import { createApiClient } from "../lib/api/client";
import { readApiStatus } from "../lib/api/status";
import { publicApiBaseUrl } from "../lib/env/client";
import { serverEnvironment } from "../lib/env/server";

export const dynamic = "force-dynamic";

const AVAILABLE_NOW = [
  "A versioned HTTP API under /api/v1 with a published OpenAPI snapshot.",
  "Liveness, readiness, capability, and contract-version endpoints.",
  "Content-addressed object storage with SHA-256 verification of every object.",
  "A transactional job queue and a worker that reports progress and terminal status.",
] as const;

const NOT_YET_AVAILABLE = [
  "Dataset upload and the column-mapping workflow.",
  "Spatial interpolation and the temporal animation pipeline.",
  "Model training, cross-validation, and explainability outputs.",
  "Export bundles and the reproducibility manifest of a published study.",
] as const;

export default async function HomePage() {
  const client = createApiClient({
    baseUrl: serverEnvironment.BACKEND_API_ORIGIN,
    timeoutMs: serverEnvironment.TRENDSMAPP_API_TIMEOUT_MS,
  });
  const status = await readApiStatus(client, { includeCapabilities: true });

  return (
    <div className="space-y-10">
      <section className="space-y-4">
        <p className="text-sm font-semibold uppercase tracking-wide text-sky-700">
          Environmental analysis with an auditable trail
        </p>
        <h1 className="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
          Trendsmapp
        </h1>
        <p className="max-w-3xl text-base leading-7 text-slate-700">
          Trendsmapp ingests environmental observations, normalizes them into a
          canonical record, validates them explicitly, and produces spatial
          surfaces, temporal animations, and machine-learning results that can be
          traced back to the exact bytes, code version, and parameters that
          produced them.
        </p>
        <p className="max-w-3xl text-sm leading-6 text-slate-600">
          The scientific work runs in the backend worker. This frontend renders
          the published contract and the live status of that service; it never
          computes a result itself.
        </p>
      </section>

      <ApiStatusPanel initialStatus={status} publicApiBaseUrl={publicApiBaseUrl} />

      <section className="grid gap-6 lg:grid-cols-2">
        <article className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold">Available in this deployment</h2>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6 text-slate-700">
            {AVAILABLE_NOW.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </article>
        <article className="rounded-xl border border-slate-200 bg-white p-6 shadow-sm">
          <h2 className="text-lg font-semibold">Not available yet</h2>
          <p className="mt-2 text-sm leading-6 text-slate-600">
            The rebuild ships one capability at a time. A control that cannot
            work is not shown, and a capability that is not implemented is not
            announced by the API.
          </p>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-sm leading-6 text-slate-700">
            {NOT_YET_AVAILABLE.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </article>
      </section>
    </div>
  );
}
