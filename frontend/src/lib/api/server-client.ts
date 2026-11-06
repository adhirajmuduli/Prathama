import "server-only";

import { createApiClient } from "../api/client";
import { serverEnvironment } from "../env/server";

/**
 * The server-side API client.
 *
 * Server components talk to the backend through the internal origin, which the
 * browser never needs to know.
 */
export function createServerApiClient() {
  return createApiClient({
    baseUrl: serverEnvironment.BACKEND_API_ORIGIN,
    timeoutMs: serverEnvironment.TRENDSMAPP_API_TIMEOUT_MS,
  });
}
