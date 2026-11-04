import { z } from "zod";

/**
 * Public environment.
 *
 * The values are inlined at build time by the bundler. They contain no
 * secret: the browser only ever learns the origin of the public API.
 */
const clientEnvironmentSchema = z.object({
  NEXT_PUBLIC_API_BASE_URL: z.string().url().nullish(),
  NEXT_PUBLIC_SITE_URL: z.string().url().nullish(),
});

export const clientEnvironment = clientEnvironmentSchema.parse({
  NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
  NEXT_PUBLIC_SITE_URL: process.env.NEXT_PUBLIC_SITE_URL,
});

export const publicApiBaseUrl = clientEnvironment.NEXT_PUBLIC_API_BASE_URL ?? null;
