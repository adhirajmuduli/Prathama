"use client";

/**
 * The contact form: name, email, subject, message, consent, and the Turnstile
 * token. Submission states are explicit; a failed or expired token blocks
 * submission until the widget produces a fresh one.
 */

import { useCallback, useState } from "react";

import { TurnstileWidget } from "./turnstile-widget";
import { contactFormSchema, type ContactFormValues } from "./contact.schemas";
import { publicTurnstileSiteKey } from "../../lib/env/client";
import { StatusBanner } from "../../components/status-banner";

type SubmissionState =
  | { readonly kind: "idle" }
  | { readonly kind: "submitting" }
  | { readonly kind: "success"; readonly requestId: string }
  | { readonly kind: "error"; readonly message: string };

const EMPTY: ContactFormValues = {
  name: "",
  email: "",
  subject: "",
  message: "",
  consent: false as unknown as true,
  turnstileToken: "",
  website: "",
};

export function ContactForm() {
  const [values, setValues] = useState<ContactFormValues>(EMPTY);
  const [state, setState] = useState<SubmissionState>({ kind: "idle" });
  const [token, setToken] = useState<string | null>(null);

  const update = <K extends keyof ContactFormValues>(
    key: K,
    value: ContactFormValues[K],
  ) => {
    setValues((current) => ({ ...current, [key]: value }));
  };

  const onVerify = useCallback((freshToken: string) => {
    setToken(freshToken);
    setValues((current) => ({ ...current, turnstileToken: freshToken }));
  }, []);

  const onTokenLost = useCallback(() => {
    setToken(null);
    setValues((current) => ({ ...current, turnstileToken: "" }));
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const parsed = contactFormSchema.safeParse({
      ...values,
      turnstileToken: token ?? "",
    });
    if (!parsed.success) {
      const first = parsed.error.issues[0];
      setState({
        kind: "error",
        message: first !== undefined ? first.message : "Please check the form.",
      });
      return;
    }
    setState({ kind: "submitting" });
    try {
      const response = await fetch("/api/contact", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed.data),
      });
      if (response.ok) {
        const payload = (await response.json()) as { request_id?: string };
        setState({ kind: "success", requestId: payload.request_id ?? "—" });
        setValues(EMPTY);
        setToken(null);
        return;
      }
      const payload = (await response.json().catch(() => null)) as {
        error?: string;
      } | null;
      setState({
        kind: "error",
        message:
          payload?.error ??
          "The message could not be sent. Please try again later.",
      });
    } catch {
      setState({
        kind: "error",
        message: "The message could not be sent. Please try again later.",
      });
    }
  };

  if (publicTurnstileSiteKey === null) {
    return (
      <StatusBanner
        tone="warning"
        title="Contact is not configured"
        description="This deployment has no Turnstile site key, so the contact form is disabled."
      />
    );
  }

  return (
    <form
      onSubmit={(event) => void submit(event)}
      className="space-y-4"
      noValidate
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Name</span>
          <input
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={values.name}
            onChange={(event) => update("name", event.target.value)}
            required
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-slate-700">Email</span>
          <input
            type="email"
            className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
            value={values.email}
            onChange={(event) => update("email", event.target.value)}
            required
          />
        </label>
      </div>
      <label className="block text-sm">
        <span className="font-medium text-slate-700">Subject</span>
        <input
          className="mt-1 w-full rounded border border-slate-300 px-2 py-1"
          value={values.subject}
          onChange={(event) => update("subject", event.target.value)}
          required
        />
      </label>
      <label className="block text-sm">
        <span className="font-medium text-slate-700">Message</span>
        <textarea
          className="mt-1 min-h-32 w-full rounded border border-slate-300 px-2 py-1"
          value={values.message}
          onChange={(event) => update("message", event.target.value)}
          required
        />
      </label>
      {/* Honeypot field: hidden from users, must stay empty. */}
      <label className="hidden" aria-hidden="true">
        Website
        <input
          tabIndex={-1}
          autoComplete="off"
          value={values.website ?? ""}
          onChange={(event) => update("website", event.target.value)}
        />
      </label>
      <label className="flex items-start gap-2 text-sm">
        <input
          type="checkbox"
          className="mt-1"
          checked={values.consent}
          onChange={(event) =>
            update("consent", event.target.checked as unknown as true)
          }
        />
        <span className="text-slate-700">
          I consent to this message being sent to the site operators by email.
        </span>
      </label>
      <TurnstileWidget
        siteKey={publicTurnstileSiteKey}
        onVerify={onVerify}
        onExpire={onTokenLost}
        onError={onTokenLost}
      />
      <button
        type="submit"
        disabled={state.kind === "submitting" || token === null}
        className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white transition hover:bg-slate-800 disabled:opacity-60"
      >
        {state.kind === "submitting" ? "Sending…" : "Send message"}
      </button>
      {state.kind === "success" ? (
        <StatusBanner
          tone="success"
          title="Message sent"
          description={`Thank you. Your reference is ${state.requestId}.`}
        />
      ) : null}
      {state.kind === "error" ? (
        <StatusBanner
          tone="danger"
          title="The message was not sent"
          description={state.message}
        />
      ) : null}
    </form>
  );
}
