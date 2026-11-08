import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Privacy",
  description:
    "What this deployment stores, which processors are involved, and which data is not collected.",
};

export default function PrivacyPage() {
  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">
          Privacy
        </h1>
        <p className="max-w-3xl text-base leading-7 text-slate-700">
          This deployment of Trendsmapp is read-only: it publishes the status of
          the scientific backend and the description of the project. The
          analysis workflow that accepts uploads is not part of this release.
        </p>
      </header>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold text-slate-900">
          What is collected
        </h2>
        <p className="max-w-3xl text-sm leading-6 text-slate-700">
          The pages of this site set no cookie, run no analytics script, and
          store no identifier in the browser. The only data that leaves the
          browser is a request to the public API for the service status, which
          carries a request identifier so that the request can be correlated
          with the server log of the same call.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold text-slate-900">
          Server-side records
        </h2>
        <p className="max-w-3xl text-sm leading-6 text-slate-700">
          The backend writes structured application logs that contain the
          request identifier, the route, the status code, and the duration of
          the call. The logs contain no payload body and no personal data. They
          are retained by the hosting provider according to the retention policy
          of the deployment, and they are never used to train a model.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold text-slate-900">
          Third-party processors
        </h2>
        <p className="max-w-3xl text-sm leading-6 text-slate-700">
          The site is served by Netlify and the API by a container service. The
          contact form uses three processors, each limited to the data it needs:
          Cloudflare Turnstile receives the human-check token and your network
          address to verify you are human (the server-side check is mandatory; a
          client-side token alone is never accepted); Upstash Redis stores only
          HMAC-SHA256 hashes of your network address and email address for rate
          limiting and duplicate suppression — never the raw values; and Resend
          receives the contact message (name, email, subject, message) to
          deliver it to the site operators by email.
        </p>
      </section>

      <section className="space-y-2">
        <h2 className="text-lg font-semibold text-slate-900">Uploads</h2>
        <p className="max-w-3xl text-sm leading-6 text-slate-700">
          No file can be uploaded through this deployment. When the analysis
          workflow is released, this page will state the retention period of an
          upload, how a dataset is deleted, and how a stored observation can be
          removed.
        </p>
      </section>
    </div>
  );
}
