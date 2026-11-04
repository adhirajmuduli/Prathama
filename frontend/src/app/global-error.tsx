"use client";

export default function GlobalError({
  error,
  reset,
}: {
  readonly error: Error & { digest?: string };
  readonly reset: () => void;
}) {
  return (
    <html lang="en">
      <body className="flex min-h-screen items-center justify-center bg-slate-50 px-4 text-slate-900">
        <main className="max-w-xl space-y-4 text-center">
          <h1 className="text-2xl font-bold tracking-tight">
            The application could not start
          </h1>
          <p className="text-sm leading-6 text-slate-700">
            An unexpected failure occurred before the page could be rendered.
            {error.digest === undefined
              ? null
              : ` The request identifier is ${error.digest}.`}
          </p>
          <button
            type="button"
            onClick={reset}
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sky-600"
          >
            Reload the application
          </button>
        </main>
      </body>
    </html>
  );
}
