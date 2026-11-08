/**
 * Safe URL, download filename, and external-link policies.
 *
 * The frontend renders links and downloads whose targets come from API
 * payloads, so every external target passes through these predicates. Only
 * http(s) URLs are allowed; `javascript:`, `data:`, and other schemes are
 * rejected, and download filenames are reduced to a safe basename.
 */

const ALLOWED_PROTOCOLS = new Set(["http:", "https:"]);

export function isSafeExternalUrl(candidate: string): boolean {
  try {
    const url = new URL(candidate);
    return ALLOWED_PROTOCOLS.has(url.protocol);
  } catch {
    return false;
  }
}

export function safeExternalUrl(candidate: string, fallback = "/"): string {
  return isSafeExternalUrl(candidate) ? candidate : fallback;
}

export function safeDownloadFilename(
  name: string,
  fallback = "download.bin",
): string {
  const basename = name.split(/[\\/]/).pop() ?? "";
  const cleaned = basename.replace(/[^\w.-]+/g, "_").replace(/^\.+/, "");
  return cleaned.length > 0 && cleaned.length <= 200 ? cleaned : fallback;
}
