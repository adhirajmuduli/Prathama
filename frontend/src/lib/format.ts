const BYTE_UNITS = ["B", "KiB", "MiB", "GiB", "TiB"] as const;

/** Format a byte count with a binary unit. */
export function formatBytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) {
    return "not available";
  }
  let size = value;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < BYTE_UNITS.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  const rendered = unitIndex === 0 ? String(size) : size.toFixed(1);
  return `${rendered} ${BYTE_UNITS[unitIndex] ?? "B"}`;
}

/** Format a duration given in milliseconds. */
export function formatDuration(milliseconds: number): string {
  if (!Number.isFinite(milliseconds) || milliseconds < 0) {
    return "not available";
  }
  if (milliseconds < 1000) {
    return `${Math.round(milliseconds)} ms`;
  }
  return `${(milliseconds / 1000).toFixed(1)} s`;
}

/** Format an ISO timestamp for display, keeping the exact value available. */
export function formatTimestamp(value: string): string {
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toISOString().replace("T", " ").replace(".000Z", " UTC");
}

/** Shorten a SHA-256 digest for display without losing its identity. */
export function formatSha256Prefix(digest: string): string {
  if (digest.length <= 16) {
    return digest;
  }
  return `${digest.slice(0, 16)}…`;
}
