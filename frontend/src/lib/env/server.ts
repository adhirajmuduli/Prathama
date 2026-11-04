import "server-only";

import { z } from "zod";

/**
 * Server-side environment.
 *
 * The values are validated once at import time so that a misconfigured
 * deployment fails at build time instead of at the first request. Only the
 * server may read this module.
 */
const serverEnvironmentSchema = z.object({
  BACKEND_API_ORIGIN: z.string().url(),
  NEXT_PUBLIC_SITE_URL: z.string().url(),
  TRENDSMAPP_API_TIMEOUT_MS: z.coerce.number().int().positive().max(60_000),
});

export const serverEnvironment = serverEnvironmentSchema.parse({
  BACKEND_API_ORIGIN: process.env.BACKEND_API_ORIGIN ?? "http://localhost:8000",
  NEXT_PUBLIC_SITE_URL: process.env.NEXT_PUBLIC_SITE_URL ?? "http://localhost:3000",
  TRENDSMAPP_API_TIMEOUT_MS: process.env.TRENDSMAPP_API_TIMEOUT_MS ?? "10000",
});
