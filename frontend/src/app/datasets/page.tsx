import Link from "next/link";

import { createServerApiClient } from "../../lib/api/server-client";
import { datasetListSchema } from "../../lib/contracts/ingest";
import { formatTimestamp } from "../../lib/format";

export const dynamic = "force-dynamic";

export default async function DatasetsPage() {
  const client = createServerApiClient();
  let body;
  let loadError: string | null = null;
  try {
    body = await client.getJson("/api/v1/datasets", datasetListSchema);
  } catch (error) {
    loadError =
      error instanceof Error
        ? error.message
        : "The dataset list could not be loaded.";
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-baseline justify-between gap-3">
        <div className="space-y-2">
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">
            Datasets
          </h1>
          <p className="max-w-3xl text-sm leading-6 text-slate-700">
            Every dataset version created from an upload. Versions are sealed
            and immutable once the ingest job succeeds.
          </p>
        </div>
        <Link
          href="/upload"
          className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800"
        >
          Upload a dataset
        </Link>
      </header>

      {loadError !== null ? (
        <p
          role="alert"
          className="rounded border border-rose-300 bg-rose-50 px-3 py-2 text-sm text-rose-900"
        >
          {loadError}
        </p>
      ) : null}

      {body !== undefined && body.items.length === 0 ? (
        <p className="text-sm text-slate-600">
          No datasets yet. Upload a file to create the first one.
        </p>
      ) : null}

      <ul className="space-y-3">
        {body?.items.map((dataset) => (
          <li key={dataset.dataset_id}>
            <Link
              href={`/datasets/${dataset.dataset_id}`}
              className="block rounded-xl border border-slate-200 bg-white p-4 shadow-sm transition hover:border-sky-400"
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="text-sm font-semibold text-slate-900">
                  {dataset.name}
                </span>
                <span className="font-mono text-xs text-slate-500">
                  {dataset.dataset_id.slice(0, 12)}…
                </span>
              </div>
              {dataset.description !== null &&
              dataset.description !== undefined ? (
                <p className="mt-1 text-sm text-slate-600">
                  {dataset.description}
                </p>
              ) : null}
              <p className="mt-1 text-xs text-slate-500">
                Updated {formatTimestamp(dataset.updated_at)}
                {dataset.current_version_id !== null &&
                dataset.current_version_id !== undefined
                  ? ` · current version ${dataset.current_version_id.slice(0, 12)}…`
                  : " · no sealed version yet"}
              </p>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
