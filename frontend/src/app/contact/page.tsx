import type { Metadata } from "next";

import { ContactForm } from "../../features/contact/contact-form";

export const metadata: Metadata = {
  title: "Contact",
  description:
    "Send a message to the Trendsmapp operators. Protected by a human check and rate limits.",
};

export default function ContactPage() {
  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">
          Contact
        </h1>
        <p className="max-w-3xl text-base leading-7 text-slate-700">
          Use this form to reach the site operators. The message is protected by
          a Cloudflare Turnstile human check, rate-limited per network and per
          email address, and delivered through a transactional email provider.
          See the privacy page for exactly which processors receive what.
        </p>
      </header>
      <div className="max-w-2xl">
        <ContactForm />
      </div>
    </div>
  );
}
