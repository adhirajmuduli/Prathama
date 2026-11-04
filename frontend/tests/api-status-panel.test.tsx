import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";

import { ApiStatusPanel } from "@/components/api-status-panel";
import type { ApiStatus } from "@/lib/api/status";

function renderWithClient(element: ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>{element}</QueryClientProvider>,
  );
}

describe("ApiStatusPanel", () => {
  it("states that the backend does not answer", () => {
    const status: ApiStatus = {
      reachable: false,
      live: null,
      ready: null,
      versions: null,
      capabilities: null,
      problem: "The API could not be reached.",
    };

    renderWithClient(
      <ApiStatusPanel initialStatus={status} publicApiBaseUrl={null} />,
    );

    expect(
      screen.getByRole("heading", { name: "Service status" }),
    ).toBeInTheDocument();
    expect(screen.getByText("The backend is not answering")).toBeInTheDocument();
    expect(screen.getByText("The API could not be reached.")).toBeInTheDocument();
  });

  it("shows the live contract versions of a ready backend", () => {
    const status: ApiStatus = {
      reachable: true,
      live: { status: "ok", service: "trendsmapp" },
      ready: {
        status: "ready",
        components: { database: "ok", object_store: "ok" },
      },
      versions: {
        api_major: 1,
        application_version: "0.1.0",
        artifact_schema_version: "1.0.0",
        recipe_schema_version: "1.0.0",
        supported_api_majors: [1],
        supported_artifact_schema_versions: ["1.0.0"],
        supported_recipe_schema_versions: ["1.0.0"],
      },
      capabilities: null,
      problem: null,
    };

    renderWithClient(
      <ApiStatusPanel initialStatus={status} publicApiBaseUrl={null} />,
    );

    expect(screen.getByText("0.1.0")).toBeInTheDocument();
    expect(screen.getByText("1 (supported: 1)")).toBeInTheDocument();
  });
});
