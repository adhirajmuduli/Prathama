import { randomUUID } from "node:crypto";

import "server-only";

import { contactRequestSchema } from "../../../features/contact/contact.schemas";
import { renderContactEmail } from "../../../features/contact/email-template";
import {
  checkRateLimit,
  claimIdempotencyKey,
  ContactProviderError,
  hashIdentifier,
  sendEmail,
  verifyTurnstile,
  type ContactProviderConfig,
} from "../../../lib/contact/providers";
import { serverEnvironment } from "../../../lib/env/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

const TURNSTILE_SITEVERIFY_URL =
  "https://challenges.cloudflare.com/turnstile/v0/siteverify";
const RESEND_API_URL = "https://api.resend.com/emails";

function jsonResponse(
  status: number,
  body: Record<string, unknown>,
  requestId: string,
) {
  return new Response(JSON.stringify({ ...body, request_id: requestId }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function providerConfig(): ContactProviderConfig | null {
  const env = serverEnvironment;
  if (
    !env.TURNSTILE_SECRET_KEY ||
    !env.UPSTASH_REST_URL ||
    !env.UPSTASH_REST_TOKEN ||
    !env.RESEND_API_KEY ||
    !env.CONTACT_FROM_EMAIL ||
    !env.CONTACT_TO_EMAIL
  ) {
    return null;
  }
  return {
    turnstileSecretKey: env.TURNSTILE_SECRET_KEY,
    turnstileSiteverifyUrl: TURNSTILE_SITEVERIFY_URL,
    upstashRestUrl: env.UPSTASH_REST_URL,
    upstashRestToken: env.UPSTASH_REST_TOKEN,
    resendApiKey: env.RESEND_API_KEY,
    resendApiUrl: RESEND_API_URL,
    hashSecret: env.CONTACT_HASH_SECRET ?? env.TURNSTILE_SECRET_KEY,
  };
}

function clientIp(request: Request): string {
  const forwarded = request.headers.get("x-forwarded-for");
  if (forwarded !== null) {
    const first = forwarded.split(",")[0]?.trim();
    if (first !== undefined && first.length > 0) {
      return first;
    }
  }
  return "unknown";
}

export async function POST(request: Request): Promise<Response> {
  const requestId = randomUUID();

  const config = providerConfig();
  if (config === null) {
    return jsonResponse(
      503,
      { error: "The contact form is not available on this deployment." },
      requestId,
    );
  }

  let payload: unknown;
  try {
    payload = await request.json();
  } catch {
    return jsonResponse(
      400,
      { error: "The request body must be JSON." },
      requestId,
    );
  }
  const parsed = contactRequestSchema.safeParse(payload);
  if (!parsed.success) {
    return jsonResponse(400, { error: "The form data is invalid." }, requestId);
  }
  const data = parsed.data;

  // Honeypot: any value in the hidden field means a bot.
  if (typeof data.website === "string" && data.website.length > 0) {
    return jsonResponse(400, { error: "The form data is invalid." }, requestId);
  }

  const ip = clientIp(request);
  const ipHash = hashIdentifier(ip, config.hashSecret);
  const emailHash = hashIdentifier(data.email.toLowerCase(), config.hashSecret);

  try {
    const turnstile = await verifyTurnstile(config, data.turnstileToken, ip);
    if (!turnstile.success) {
      return jsonResponse(
        403,
        { error: "The human check failed. Please retry." },
        requestId,
      );
    }

    const ipLimit = await checkRateLimit(
      config,
      `ip:${ipHash}`,
      serverEnvironment.CONTACT_RATE_LIMIT_IP_PER_WINDOW,
      serverEnvironment.CONTACT_RATE_LIMIT_WINDOW_MS,
    );
    if (!ipLimit.allowed) {
      return jsonResponse(
        429,
        { error: "Too many messages. Please try again later." },
        requestId,
      );
    }
    const emailLimit = await checkRateLimit(
      config,
      `email:${emailHash}`,
      serverEnvironment.CONTACT_RATE_LIMIT_EMAIL_PER_WINDOW,
      serverEnvironment.CONTACT_RATE_LIMIT_WINDOW_MS,
    );
    if (!emailLimit.allowed) {
      return jsonResponse(
        429,
        { error: "Too many messages. Please try again later." },
        requestId,
      );
    }

    const idempotencyKey = hashIdentifier(
      `${data.email.toLowerCase()}:${data.subject}:${data.message}`,
      config.hashSecret,
    );
    const claimed = await claimIdempotencyKey(
      config,
      idempotencyKey,
      serverEnvironment.CONTACT_IDEMPOTENCY_TTL_SECONDS,
    );
    if (!claimed) {
      // Duplicate of a recent submission: report success without resending.
      return jsonResponse(200, { ok: true }, requestId);
    }

    const html = renderContactEmail({
      name: data.name,
      email: data.email,
      subject: data.subject,
      message: data.message,
      requestId,
      receivedAt: new Date().toISOString(),
    });
    const result = await sendEmail(config, {
      from: serverEnvironment.CONTACT_FROM_EMAIL as string,
      to: serverEnvironment.CONTACT_TO_EMAIL as string,
      subject: `Contact: ${data.subject}`,
      html,
      replyTo: data.email,
    });

    // Redacted log line: delivery id, request id, timestamp, hashed sender only.
    console.info(
      JSON.stringify({
        event: "contact.sent",
        request_id: requestId,
        delivery_id: result.deliveryId,
        sender_hash: emailHash.slice(0, 16),
        at: new Date().toISOString(),
      }),
    );
    return jsonResponse(200, { ok: true }, requestId);
  } catch (error) {
    if (error instanceof ContactProviderError) {
      const status =
        error.code === "turnstile_unreachable"
          ? 403
          : error.code.startsWith("ratelimit")
            ? 503
            : 502;
      return jsonResponse(
        status,
        { error: "The message could not be sent. Please try again later." },
        requestId,
      );
    }
    console.error(
      JSON.stringify({ event: "contact.error", request_id: requestId }),
    );
    return jsonResponse(
      500,
      { error: "The message could not be sent. Please try again later." },
      requestId,
    );
  }
}
