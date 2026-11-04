"use client";

import { useEffect } from "react";

export default function RouteError({
  error,
  reset,
}: {
  readonly error: Error & { digest?: string };
  readonly reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-bold tracking-tight text-slate-900">
        This page could not be rendered
      </h1>
      <p className="max-w-3xl text-sm leading-6 text-slate-700">
        The request that builds this page failed. The failure is recorded in the
        server log together with the request identifier shown below.
      </p>
      {error.digest === undefined ? null : (
        <p className="text-sm text-slate-600">
          Request identifier: <code className="font-mono">{error.digest}</code>
        </p>
      )}
      <button
        type="button"
        onClick={reset}
        className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sky-600"
      >
        Try again
      </button>
    </div>
  );
}
