import type { Metadata } from "next";
import type { ReactNode } from "react";

import { AppShell } from "../components/app-shell";
import { AppProviders } from "../providers/app-providers";
import { serverEnvironment } from "../lib/env/server";
import "./globals.css";

export const metadata: Metadata = {
  metadataBase: new URL(serverEnvironment.NEXT_PUBLIC_SITE_URL),
  title: {
    default: "Trendsmapp",
    template: "%s | Trendsmapp",
  },
  description:
    "Trendsmapp publishes validated environmental spatial analysis, temporal animation, and leakage-resistant machine learning with a full provenance trail.",
  applicationName: "Trendsmapp",
  openGraph: {
    title: "Trendsmapp",
    description:
      "Validated environmental spatial analysis with reproducible, auditable outputs.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  readonly children: ReactNode;
}) {
  return (
    <html lang="en">
      <body className="antialiased">
        <a className="skip-link" href="#main-content">
          Skip to the main content
        </a>
        <AppProviders>
          <AppShell>{children}</AppShell>
        </AppProviders>
      </body>
    </html>
  );
}
