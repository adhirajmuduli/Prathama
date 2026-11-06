import Link from "next/link";

import { VersionExplorer } from "../../../components/datasets/version-explorer";
import { createServerApiClient } from "../../../lib/api/server-client";
import { datasetSchema, datasetVersionListSchema } from "../../../lib/contracts/ingest";
import { formatTimestamp } from "../../../lib/format";

export const dynamic = "force-dynamic";

export default async function DatasetDetailPage({
  params,
}: {
  readonly params: Promise<{ datasetId: string }>;
}) {
  const { datasetId } = await params;
  const client = createServerApiClient();
  const dataset = await client.getJson(`/api/v1/datasets/${datasetId}`, datasetSchema);
  const versions = await client.getJson(
    `/api/v1/datasets/${datasetId}/versions`,
    datasetVersionListSchema,
  );

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <nav className="text-xs text-slate-500">
          <Link href="/datasets" className="hover:underline">
            Datasets
          </Link>{" "}
          / {dataset.name}
        </nav>
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">{dataset.name}</h1>
        {dataset.description !== null && dataset.description !== undefined ? (
          <p className="max-w-3xl text-sm leading-6 text-slate-700">{dataset.description}</p>
        ) : null}
        <p className="font-mono text-xs text-slate-500">
          {dataset.dataset_id} · created {formatTimestamp(dataset.created_at)}
        </p>
      </header>

      <VersionExplorer versions={versions.items} />
    </div>
  );
}
