import type { ApiClient } from "./client";
import { describeError } from "./errors";
import type {
  Capabilities,
  ContractVersions,
  HealthLive,
  HealthReady,
} from "../contracts/runtime";
import {
  capabilitiesSchema,
  contractVersionsSchema,
  healthLiveSchema,
  healthReadySchema,
} from "../contracts/runtime";

export interface ApiStatus {
  readonly reachable: boolean;
  readonly live: HealthLive | null;
  readonly ready: HealthReady | null;
  readonly versions: ContractVersions | null;
  readonly capabilities: Capabilities | null;
  readonly problem: string | null;
}

export interface ApiStatusOptions {
  readonly includeCapabilities?: boolean;
}

/**
 * Read the live status of the backend.
 *
 * Every call is independent: a backend that answers the liveness probe but
 * not the readiness probe still produces a truthful status, and an
 * unreachable backend produces an explicit problem instead of invented data.
 */
export async function readApiStatus(
  client: ApiClient,
  options: ApiStatusOptions = {},
): Promise<ApiStatus> {
  const calls: Promise<unknown>[] = [
    client.getJson("/api/v1/health/live", healthLiveSchema),
    client.getJson("/api/v1/health/ready", healthReadySchema),
    client.getJson("/api/v1/contracts/versions", contractVersionsSchema),
  ];
  if (options.includeCapabilities === true) {
    calls.push(client.getJson("/api/v1/capabilities", capabilitiesSchema));
  }

  const results = await Promise.allSettled(calls);
  const live = readResult<HealthLive>(results[0]);
  const ready = readResult<HealthReady>(results[1]);
  const versions = readResult<ContractVersions>(results[2]);
  const capabilities = readResult<Capabilities>(results[3]);

  const problems = results
    .filter(
      (result): result is PromiseRejectedResult => result.status === "rejected",
    )
    .map((result) => describeError(result.reason));

  return {
    reachable: live !== null,
    live,
    ready,
    versions,
    capabilities,
    problem: problems.length === 0 ? null : problems.join("; "),
  };
}

function readResult<T>(
  result: PromiseSettledResult<unknown> | undefined,
): T | null {
  if (result === undefined || result.status !== "fulfilled") {
    return null;
  }
  return result.value as T;
}
