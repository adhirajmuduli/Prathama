export default function Loading() {
  return (
    <div role="status" aria-live="polite" className="space-y-4">
      <p className="text-sm text-slate-600">
        Loading the current service status…
      </p>
      <div className="h-32 animate-pulse rounded-xl border border-slate-200 bg-white" />
    </div>
  );
}
