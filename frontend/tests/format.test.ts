import { describe, expect, it } from "vitest";

import {
  formatBytes,
  formatDuration,
  formatSha256Prefix,
  formatTimestamp,
} from "@/lib/format";

describe("formatBytes", () => {
  it("renders binary units", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(1024)).toBe("1.0 KiB");
    expect(formatBytes(5 * 1024 * 1024)).toBe("5.0 MiB");
  });

  it("refuses a negative size", () => {
    expect(formatBytes(-1)).toBe("not available");
  });
});

describe("formatDuration", () => {
  it("renders milliseconds and seconds", () => {
    expect(formatDuration(250)).toBe("250 ms");
    expect(formatDuration(1500)).toBe("1.5 s");
  });
});

describe("formatTimestamp", () => {
  it("keeps an unparsable value unchanged", () => {
    expect(formatTimestamp("not a timestamp")).toBe("not a timestamp");
  });

  it("renders a parsable timestamp", () => {
    expect(formatTimestamp("2026-10-27T09:30:00Z")).toBe(
      "2026-10-27 09:30:00 UTC",
    );
  });
});

describe("formatSha256Prefix", () => {
  it("shortens a digest without losing its identity", () => {
    const digest = "a".repeat(64);
    expect(formatSha256Prefix(digest)).toBe(`${"a".repeat(16)}…`);
  });
});
