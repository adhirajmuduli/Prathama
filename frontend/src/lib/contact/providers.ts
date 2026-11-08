import "server-only";

/**
 * Server-only providers for the contact route: Cloudflare Turnstile
 * Siteverify, Upstash Redis (rate limiting and idempotency), and Resend.
 *
 * Each provider is called through its REST API with the platform `fetch`, so
 * no SDK dependency ships to the client bundle. Every function throws a
 * typed `ContactProviderError` with a safe, loggable code; raw identifiers
 * never leave this module.
 */

import { createHmac, randomUUID } from "node:crypto";

export class ContactProviderError extends Error {
  readonly code: string;

  constructor(code: string, message: string) {
    super(message);
    this.name = "ContactProviderError";
    this.code = code;
  }
}

export interface ContactProviderConfig {
  readonly turnstileSecretKey: string;
  readonly turnstileSiteverifyUrl: string;
  readonly upstashRestUrl: string;
  readonly upstashRestToken: string;
  readonly resendApiKey: string;
  readonly resendApiUrl: string;
  readonly hashSecret: string;
}

export interface TurnstileVerification {
  readonly success: boolean;
  readonly errorCodes: readonly string[];
}

export async function verifyTurnstile(
  config: ContactProviderConfig,
  token: string,
  remoteIp: string,
  fetchImplementation: typeof fetch = fetch,
): Promise<TurnstileVerification> {
  const body = new URLSearchParams({
    secret: config.turnstileSecretKey,
    response: token,
    remoteip: remoteIp,
  });
  let response: Response;
  try {
    response = await fetchImplementation(config.turnstileSiteverifyUrl, {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: body.toString(),
    });
  } catch {
    throw new ContactProviderError(
      "turnstile_unreachable",
      "The human check could not be verified.",
    );
  }
  if (!response.ok) {
    throw new ContactProviderError(
      "turnstile_unreachable",
      "The human check could not be verified.",
    );
  }
  const payload = (await response.json()) as {
    success?: boolean;
    "error-codes"?: string[];
  };
  return {
    success: payload.success === true,
    errorCodes: payload["error-codes"] ?? [],
  };
}

/** HMAC-SHA256 of a network identifier: raw addresses are never stored. */
export function hashIdentifier(value: string, secret: string): string {
  return createHmac("sha256", secret).update(value).digest("hex");
}

const SLIDING_WINDOW_SCRIPT = `
local key = KEYS[1]
local window_ms = tonumber(ARGV[1])
local limit = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', key, '-inf', now - window_ms)
local count = redis.call('ZCARD', key)
if count < limit then
  local member = redis.call('INCR', key .. ':seq')
  redis.call('ZADD', key, now, now .. ':' .. member)
  redis.call('PEXPIRE', key, window_ms)
  redis.call('PEXPIRE', key .. ':seq', window_ms)
  return {1, count + 1}
end
return {0, count}
`;

const IDEMPOTENCY_SCRIPT = `
local created = redis.call('SET', KEYS[1], ARGV[1], 'NX', 'EX', tonumber(ARGV[2]))
if created then
  return 1
end
return 0
`;

async function upstashEval(
  config: ContactProviderConfig,
  script: string,
  keys: readonly string[],
  args: readonly (string | number)[],
  fetchImplementation: typeof fetch,
): Promise<unknown> {
  let response: Response;
  try {
    response = await fetchImplementation(`${config.upstashRestUrl}/eval`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${config.upstashRestToken}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ script, keys: [...keys], args: args.map(String) }),
    });
  } catch {
    throw new ContactProviderError(
      "ratelimit_unreachable",
      "The rate limiter could not be reached.",
    );
  }
  if (!response.ok) {
    throw new ContactProviderError(
      "ratelimit_unreachable",
      "The rate limiter could not be reached.",
    );
  }
  const payload = (await response.json()) as {
    result?: unknown;
    error?: string;
  };
  if (payload.error !== undefined) {
    throw new ContactProviderError(
      "ratelimit_error",
      "The rate limiter rejected the request.",
    );
  }
  return payload.result;
}

export interface RateLimitDecision {
  readonly allowed: boolean;
  readonly remaining: number;
}

/** Sliding-window rate limit over one hashed key. */
export async function checkRateLimit(
  config: ContactProviderConfig,
  key: string,
  limit: number,
  windowMs: number,
  fetchImplementation: typeof fetch = fetch,
): Promise<RateLimitDecision> {
  const result = (await upstashEval(
    config,
    SLIDING_WINDOW_SCRIPT,
    [`contact:rl:${key}`],
    [windowMs, limit, Date.now()],
    fetchImplementation,
  )) as [number, number];
  const allowed = result[0] === 1;
  return { allowed, remaining: Math.max(0, limit - result[1]) };
}

/** Returns true when the idempotency key was newly claimed. */
export async function claimIdempotencyKey(
  config: ContactProviderConfig,
  key: string,
  ttlSeconds: number,
  fetchImplementation: typeof fetch = fetch,
): Promise<boolean> {
  const result = await upstashEval(
    config,
    IDEMPOTENCY_SCRIPT,
    [`contact:idem:${key}`],
    [randomUUID(), ttlSeconds],
    fetchImplementation,
  );
  return result === 1;
}

export interface EmailPayload {
  readonly from: string;
  readonly to: string;
  readonly subject: string;
  readonly html: string;
  readonly replyTo: string;
}

export interface SendResult {
  readonly deliveryId: string | null;
}

export async function sendEmail(
  config: ContactProviderConfig,
  payload: EmailPayload,
  fetchImplementation: typeof fetch = fetch,
): Promise<SendResult> {
  let response: Response;
  try {
    response = await fetchImplementation(config.resendApiUrl, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${config.resendApiKey}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        from: payload.from,
        to: [payload.to],
        reply_to: payload.replyTo,
        subject: payload.subject,
        html: payload.html,
      }),
    });
  } catch {
    throw new ContactProviderError(
      "email_unreachable",
      "The message could not be sent.",
    );
  }
  if (!response.ok) {
    throw new ContactProviderError(
      "email_failed",
      "The message could not be sent.",
    );
  }
  const body = (await response.json()) as { id?: string };
  return { deliveryId: typeof body.id === "string" ? body.id : null };
}
