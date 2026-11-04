import { QueryClient } from "@tanstack/react-query";

/**
 * Create the query client used by the browser.
 *
 * Scientific results are never cached across sessions: the cache exists only
 * to avoid repeating a read while the user is looking at the same page.
 */
export function createQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 15_000,
        gcTime: 5 * 60_000,
        retry: 1,
        refetchOnWindowFocus: false,
      },
    },
  });
}
