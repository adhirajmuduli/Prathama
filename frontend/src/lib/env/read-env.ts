/**
 * Read one environment variable, treating an empty or whitespace-only value
 * as unset. Deployment platforms often keep a variable present but blank when
 * it should be absent; `??` alone does not catch that, and a blank URL would
 * fail schema validation at module load and take down every page.
 *
 * This module must stay free of `server-only` so both the client and the
 * server environment modules can use it.
 */
export function readEnv(name: string): string | undefined {
  const value = process.env[name];
  if (value === undefined) {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length === 0 ? undefined : trimmed;
}
