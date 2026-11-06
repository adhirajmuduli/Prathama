"use client";

/**
 * The upload flow: pick a file, upload it in chunks, read the probe, confirm
 * the column mapping, create the dataset, and follow the ingest job to its
 * terminal state.
 */

import { useCallback, useMemo, useRef, useState } from "react";

import Link from "next/link";

import { MappingForm } from "../../components/upload/mapping-form";
import { StatusBanner } from "../../components/status-banner";
import { createApiClient } from "../../lib/api/client";
import { uploadFile, type UploadProgress, type UploadResult } from "../../lib/api/uploader";
import { publicApiBaseUrl } from "../../lib/env/client";
import {
  createDatasetResponseSchema,
  jobSchema,
  probeSchema,
  type ColumnMapping,
  type CompleteUpload,
  type Job,
  type Probe,
} from "../../lib/contracts/ingest";
import { formatBytes } from "../../lib/format";

type Step = "idle" | "uploading" | "probing" | "mapping" | "creating" | "running" | "done" | "failed";

const TERMINAL_JOB_STATES = new Set(["succeeded", "failed", "cancelled"]);

export default function UploadPage() {
  const client = useMemo(
    () => (publicApiBaseUrl === null ? null : createApiClient({ baseUrl: publicApiBaseUrl })),
    [],
  );
  const [step, setStep] = useState<Step>("idle");
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<UploadProgress | null>(null);
  const [upload, setUpload] = useState<UploadResult | null>(null);
  const [probe, setProbe] = useState<Probe | null>(null);
  const [completion, setCompletion] = useState<CompleteUpload | null>(null);
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [versionId, setVersionId] = useState<string | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const startUpload = useCallback(
    async (file: File) => {
      if (client === null) {
        setError("The public API origin is not configured, so uploads are disabled.");
        return;
      }
      setStep("uploading");
      setError(null);
      setProgress(null);
      try {
        const result = await uploadFile(client, file, file.name, {
          contentType: file.type || null,
          onProgress: setProgress,
        });
        setUpload(result);
        setCompletion(result.completion);
        setStep("probing");
        const probeResponse = await client.postEmpty(
          `/api/v1/uploads/${result.session.upload_id}/probe`,
          probeSchema,
        );
        setProbe(probeResponse);
        setStep("mapping");
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "The upload failed.");
        setStep("failed");
      }
    },
    [client],
  );

  const submitMapping = useCallback(
    async (mapping: ColumnMapping) => {
      if (client === null || upload === null || probe === null) {
        return;
      }
      setStep("creating");
      setError(null);
      try {
        const created = await client.postJson(
          "/api/v1/datasets",
          {
            upload_id: upload.session.upload_id,
            name: upload.session.filename,
            mapping,
          },
          createDatasetResponseSchema,
        );
        setDatasetId(created.dataset_id);
        setVersionId(created.version_id);
        setStep("running");
        await pollJob(client, created.job_id, setJob);
        setStep("done");
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Creating the dataset failed.");
        setStep("failed");
      }
    },
    [client, upload, probe],
  );

  const onFilePicked = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file !== undefined) {
      void startUpload(file);
    }
  };

  if (client === null) {
    return (
      <div className="space-y-4">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">Upload a dataset</h1>
        <StatusBanner
          tone="warning"
          title="Uploads are not available"
          description="This deployment has no public API origin configured (NEXT_PUBLIC_API_BASE_URL), so no file can be sent to the backend from the browser. The server-rendered pages still work."
        />
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">Upload a dataset</h1>
        <p className="max-w-3xl text-sm leading-6 text-slate-700">
          Choose a CSV, TSV, XLSX, or Parquet file. It is uploaded in verified chunks, probed,
          and then you confirm the column mapping before the dataset version is created and
          sealed by the worker.
        </p>
      </header>

      {step === "idle" || step === "failed" ? (
        <section className="space-y-4">
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv,.tsv,.xlsx,.parquet"
            onChange={onFilePicked}
            className="block w-full max-w-xl text-sm text-slate-700 file:mr-4 file:rounded-lg file:border-0 file:bg-slate-900 file:px-4 file:py-2 file:text-sm file:font-semibold file:text-white hover:file:bg-slate-800"
          />
          {step === "failed" && error !== null ? (
            <StatusBanner tone="danger" title="The upload failed" description={error} />
          ) : null}
        </section>
      ) : null}

      {step === "uploading" && progress !== null ? (
        <section className="space-y-2">
          <p className="text-sm text-slate-700">
            Uploading part {progress.currentPart ?? progress.uploadedParts} of{" "}
            {progress.totalParts} — {formatBytes(progress.bytesUploaded)} of{" "}
            {formatBytes(progress.totalBytes)}
          </p>
          <div className="h-2 w-full max-w-xl overflow-hidden rounded bg-slate-200">
            <div
              className="h-full bg-sky-600 transition-all"
              style={{
                width: `${Math.round((progress.bytesUploaded / progress.totalBytes) * 100)}%`,
              }}
            />
          </div>
        </section>
      ) : null}

      {step === "probing" ? (
        <StatusBanner
          tone="info"
          title="Upload complete, probing the file"
          description="Reading the first rows to detect the format, layout, and a proposed column mapping."
        />
      ) : null}

      {step === "mapping" && probe !== null ? (
        <section className="space-y-4">
          <StatusBanner
            tone="info"
            title={`Detected ${probe.file_format} layout '${probe.layout}' with ${probe.fields.length} columns`}
            description={
              probe.layout_warnings.length > 0 || probe.proposal_warnings.length > 0
                ? [...probe.layout_warnings, ...probe.proposal_warnings].join(" ")
                : "The proposed mapping follows the detected header names; confirm or correct every role."
            }
          />
          <MappingForm
            probe={probe}
            onSubmit={(mapping) => {
              void submitMapping(mapping);
            }}
            error={error}
          />
        </section>
      ) : null}

      {step === "creating" ? (
        <StatusBanner tone="info" title="Creating the dataset" description="Validating the mapping and enqueueing the ingest job." />
      ) : null}

      {step === "running" && job !== null ? (
        <StatusBanner
          tone="info"
          title={`Ingest job ${job.status}${job.stage !== null ? ` — ${job.stage}` : ""}`}
          description={`Progress ${(job.progress * 100).toFixed(0)}%. The worker parses, normalizes, runs quality control, and seals the dataset version.`}
        />
      ) : null}

      {step === "done" && datasetId !== null && versionId !== null ? (
        <section className="space-y-3">
          <StatusBanner
            tone={job?.status === "succeeded" ? "info" : "warning"}
            title={job?.status === "succeeded" ? "Dataset version sealed" : `Job ended as ${job?.status ?? "unknown"}`}
            description={
              job?.status === "succeeded"
                ? "The ingest job succeeded and the version is sealed and immutable."
                : job?.error !== null && job?.error !== undefined
                  ? `${job.error.code}: ${job.error.message}`
                  : "The ingest job did not succeed."
            }
          />
          <Link
            href={`/datasets/${datasetId}`}
            className="inline-block rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800"
          >
            Open the dataset
          </Link>
        </section>
      ) : null}

      {completion !== null && step !== "idle" ? (
        <p className="text-xs text-slate-500">
          Raw artifact {completion.artifact.sha256.slice(0, 16)}… ({formatBytes(completion.artifact.size_bytes)}),
          immutable and content-addressed.
        </p>
      ) : null}
    </div>
  );
}

async function pollJob(
  client: ReturnType<typeof createApiClient>,
  jobId: string,
  onUpdate: (job: Job) => void,
): Promise<void> {
  for (;;) {
    const job = await client.getJson(`/api/v1/jobs/${jobId}`, jobSchema);
    onUpdate(job);
    if (TERMINAL_JOB_STATES.has(job.status)) {
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}
