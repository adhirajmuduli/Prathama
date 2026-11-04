import type { MetadataRoute } from "next";

import { clientEnvironment } from "../lib/env/client";

const siteUrl = clientEnvironment.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000";

const PUBLIC_ROUTES = ["/", "/methods", "/privacy"] as const;

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();
  return PUBLIC_ROUTES.map((route) => ({
    url: `${siteUrl}${route}`,
    lastModified,
    changeFrequency: "weekly",
    priority: route === "/" ? 1 : 0.5,
  }));
}
