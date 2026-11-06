import Link from "next/link";

const NAVIGATION = [
  { href: "/", label: "Overview" },
  { href: "/upload", label: "Upload" },
  { href: "/datasets", label: "Datasets" },
  { href: "/methods", label: "Methods" },
  { href: "/privacy", label: "Privacy" },
] as const;

export function SiteHeader() {
  return (
    <header className="border-b border-slate-200 bg-white">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-6">
        <Link href="/" className="text-lg font-semibold tracking-tight text-slate-900">
          Trendsmapp
        </Link>
        <nav aria-label="Primary">
          <ul className="flex flex-wrap items-center gap-4 text-sm font-medium text-slate-700">
            {NAVIGATION.map((item) => (
              <li key={item.href}>
                <Link
                  href={item.href}
                  className="rounded px-1 py-1 transition hover:text-slate-950 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-sky-600"
                >
                  {item.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>
      </div>
    </header>
  );
}
