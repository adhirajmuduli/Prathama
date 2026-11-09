import { afterEach, describe, expect, it, vi } from "vitest";

import { readEnv } from "@/lib/env/read-env";

describe("readEnv", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("returns the value when set", () => {
    vi.stubEnv("READ_ENV_TEST_VALUE", "https://example.org");
    expect(readEnv("READ_ENV_TEST_VALUE")).toBe("https://example.org");
  });

  it("treats an empty string as unset", () => {
    vi.stubEnv("READ_ENV_TEST_EMPTY", "");
    expect(readEnv("READ_ENV_TEST_EMPTY")).toBeUndefined();
  });

  it("treats a whitespace-only string as unset and trims real values", () => {
    vi.stubEnv("READ_ENV_TEST_BLANK", "   ");
    expect(readEnv("READ_ENV_TEST_BLANK")).toBeUndefined();
    vi.stubEnv("READ_ENV_TEST_PADDED", "  https://example.org  ");
    expect(readEnv("READ_ENV_TEST_PADDED")).toBe("https://example.org");
  });

  it("returns undefined for a variable that is not set at all", () => {
    expect(readEnv("READ_ENV_TEST_DEFINITELY_UNSET")).toBeUndefined();
  });
});
