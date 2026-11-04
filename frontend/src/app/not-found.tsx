import Link from "next/link";

export default function NotFound() {
  return (
    <div className="space-y-4">
      <h1 className="text-3xl font-bold tracking-tight text-slate-900">
        This page does not exist
      </h1>
      <p className="max-w-3xl text-sm leading-6 text-slate-700">
        The address does not match any published route. The pages of this
        deployment are the overview, the methods, and the privacy statement.
      </p>
      <Link
        href="/"
        className="inline-block rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sky-600"
      >
        Return to the overview
      </Link>
    </div>
  );
}
