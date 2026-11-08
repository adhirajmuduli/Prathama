/**
 * The contact email body, rendered to an HTML string.
 *
 * Every user-supplied value passes through `escapeHtml`, so the rendered
 * markup can never contain tags injected through the form. Rendered as a
 * string (not a React component) because the App Router forbids importing
 * react-dom/server, and the Resend REST API accepts an `html` field.
 */

export interface ContactEmailProps {
  readonly name: string;
  readonly email: string;
  readonly subject: string;
  readonly message: string;
  readonly requestId: string;
  readonly receivedAt: string;
}

export function escapeHtml(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function renderContactEmail(props: ContactEmailProps): string {
  const { name, email, subject, message, requestId, receivedAt } = props;
  const body = escapeHtml(message).replaceAll("\n", "<br />");
  return [
    '<div style="font-family:sans-serif;color:#0f172a;line-height:1.5">',
    `<h1 style="font-size:18px">New contact message — ${escapeHtml(subject)}</h1>`,
    `<p><strong>From:</strong> ${escapeHtml(name)} &lt;${escapeHtml(email)}&gt;</p>`,
    `<p><strong>Received:</strong> ${escapeHtml(receivedAt)} · <strong>Request:</strong> ${escapeHtml(requestId)}</p>`,
    "<hr />",
    `<p style="white-space:pre-wrap">${body}</p>`,
    "</div>",
  ].join("");
}
