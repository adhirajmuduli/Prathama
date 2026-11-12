import { z } from "zod";

/**
 * Public environment.
 *
 * The values are inlined at build time by the bundler. They contain no
 * secret: the browser only ever learns the origin of the public API.
 *
 * NOTE: these MUST be direct `process.env.NEXT_PUBLIC_*` member accesses.
 * The bundler only inlines direct member reads; routing them through a helper
 * like `process.env[name]` silently defeats inlining and ships `undefined`
 * to the browser.
 */
function publicEnv(
  name: string,
  value: string | undefined,
): string | undefined {
  const trimmed = value?.trim();
  return trimmed ? trimmed : undefined;
}

const clientEnvironmentSchema = z.object({
  NEXT_PUBLIC_API_BASE_URL: z.string().url().nullish(),
  NEXT_PUBLIC_SITE_URL: z.string().url().nullish(),
  NEXT_PUBLIC_TURNSTILE_SITE_KEY: z.string().min(1).nullish(),
});

export const clientEnvironment = clientEnvironmentSchema.parse({
  NEXT_PUBLIC_API_BASE_URL: publicEnv(
    "NEXT_PUBLIC_API_BASE_URL",
    process.env.NEXT_PUBLIC_API_BASE_URL,
  ),
  NEXT_PUBLIC_SITE_URL: publicEnv(
    "NEXT_PUBLIC_SITE_URL",
    process.env.NEXT_PUBLIC_SITE_URL,
  ),
  NEXT_PUBLIC_TURNSTILE_SITE_KEY: publicEnv(
    "NEXT_PUBLIC_TURNSTILE_SITE_KEY",
    process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY,
  ),
});

export const publicApiBaseUrl =
  clientEnvironment.NEXT_PUBLIC_API_BASE_URL ?? null;
export const publicTurnstileSiteKey =
  clientEnvironment.NEXT_PUBLIC_TURNSTILE_SITE_KEY ?? null;
