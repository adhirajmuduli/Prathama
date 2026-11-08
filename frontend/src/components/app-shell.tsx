import type { ReactNode } from "react";

import { SiteHeader } from "./site-header";

export function AppShell({ children }: { readonly children: ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      <SiteHeader />
      <main
        id="main-content"
        className="mx-auto w-full max-w-5xl flex-1 px-4 py-10 sm:px-6"
      >
        {children}
      </main>
      <footer className="border-t border-slate-200 bg-white">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-2 px-4 py-6 text-sm text-slate-600 sm:px-6">
          <p>
            Trendsmapp rebuild. The frontend renders the published contract;
            every scientific result is produced by the backend worker.
          </p>
          <p>
            The prototype at the repository root is frozen and kept as a
            behavioral reference. This deployment exposes the rebuilt API only.
          </p>
        </div>
      </footer>
    </div>
  );
}
