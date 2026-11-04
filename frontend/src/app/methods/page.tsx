import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Methods",
  description:
    "The scientific methods Trendsmapp applies: normalization, explicit quality control, spatial and temporal interpolation, and leakage-resistant model evaluation.",
};

const SECTIONS = [
  {
    heading: "Canonical observation model",
    body: "Every ingested row is normalized into one observation record that keeps the original value, the unit, the qualifier, the station, the timestamp, and the source of the value. Raw values are never overwritten: a transformation produces a new observation and leaves the input intact.",
  },
  {
    heading: "Explicit quality control",
    body: "Quality control produces flags, not deletions. An observation that fails a range, duplicate, or consistency check is marked and reported. The analyst decides what a flagged observation means; the system never silently drops it.",
  },
  {
    heading: "Spatial interpolation",
    body: "Spatial surfaces are estimated in a projected coordinate system, never in geographic degrees. The interpolation method, its parameters, the neighbourhood definition, and the validation folds are recorded with the result so that the surface can be regenerated exactly.",
  },
  {
    heading: "Temporal animation",
    body: "Frames are scheduled from the observed timestamps and rendered from the validated surfaces. Each frame records the time it represents and the surface it was drawn from, so an animation can be mapped back to the observations that produced it.",
  },
  {
    heading: "Leakage-resistant model evaluation",
    body: "Preprocessing is fitted inside the training fold only. Tuning and final evaluation are separated, and temporal, grouped-station, and spatial-block splits are available where the data structure allows them. The reported metrics state the split that produced them.",
  },
  {
    heading: "Provenance",
    body: "Every artifact carries a SHA-256 digest, the schema version it was written with, the application version that wrote it, and the run identifier of the analysis that produced it. A reproducibility manifest collects those values together with the resolved dependency versions and the random seeds.",
  },
] as const;

export default function MethodsPage() {
  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">Methods</h1>
        <p className="max-w-3xl text-base leading-7 text-slate-700">
          This page summarizes the methods the rebuilt backend applies. The
          normative description, including the parameters and the validation
          procedure of every implementation, lives in{" "}
          <code className="rounded bg-slate-100 px-1 py-0.5 text-sm">
            docs/scientific-methods.md
          </code>{" "}
          in the repository.
        </p>
      </header>

      {SECTIONS.map((section) => (
        <section key={section.heading} className="space-y-2">
          <h2 className="text-lg font-semibold text-slate-900">{section.heading}</h2>
          <p className="max-w-3xl text-sm leading-6 text-slate-700">{section.body}</p>
        </section>
      ))}
    </div>
  );
}
