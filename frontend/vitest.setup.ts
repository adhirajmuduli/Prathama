import "@testing-library/jest-dom/vitest";

import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// The public API origin is read at module load; tests point it at the MSW server.
process.env.NEXT_PUBLIC_API_BASE_URL = "http://api.test";
process.env.NEXT_PUBLIC_SITE_URL = "http://localhost:3000";

afterEach(() => {
  cleanup();
});
