import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ContactForm } from "@/features/contact/contact-form";

const server = setupServer();

beforeAll(() => {
  server.listen({ onUnhandledFrame: "error" });
  // Minimal Turnstile stub: rendering the widget immediately yields a token.
  (window as unknown as { turnstile: unknown }).turnstile = {
    render: (
      _container: HTMLElement,
      options: { callback: (token: string) => void },
    ) => {
      setTimeout(() => options.callback("token-123"), 0);
      return "widget-1";
    },
    remove: () => undefined,
    reset: () => undefined,
  };
});

afterEach(() => {
  server.resetHandlers();
});

afterAll(() => {
  server.close();
});

function installContactEndpoint(status = 200) {
  server.use(
    http.post("http://localhost:3000/api/contact", () =>
      status === 200
        ? HttpResponse.json({ ok: true, request_id: "req-1" })
        : HttpResponse.json(
            { error: "The message could not be sent." },
            { status },
          ),
    ),
    http.post("http://localhost/api/contact", () =>
      status === 200
        ? HttpResponse.json({ ok: true, request_id: "req-1" })
        : HttpResponse.json(
            { error: "The message could not be sent." },
            { status },
          ),
    ),
  );
}

function fillForm() {
  fireEvent.change(screen.getByLabelText("Name"), {
    target: { value: "Ada Lovelace" },
  });
  fireEvent.change(screen.getByLabelText("Email"), {
    target: { value: "ada@example.org" },
  });
  fireEvent.change(screen.getByLabelText("Subject"), {
    target: { value: "Question" },
  });
  fireEvent.change(screen.getByLabelText("Message"), {
    target: { value: "A sufficiently long message body." },
  });
  fireEvent.click(screen.getByRole("checkbox"));
}

describe("ContactForm", () => {
  it("keeps the submit button disabled until the human check yields a token", async () => {
    installContactEndpoint();
    render(<ContactForm />);
    const submit = screen.getByRole("button", { name: /send message/i });
    expect(submit).toBeDisabled();
    await waitFor(() => expect(submit).toBeEnabled(), { timeout: 5_000 });
  });

  it("submits a valid form and shows the success state", async () => {
    installContactEndpoint();
    render(<ContactForm />);
    fillForm();
    const submit = screen.getByRole("button", { name: /send message/i });
    await waitFor(() => expect(submit).toBeEnabled(), { timeout: 5_000 });
    fireEvent.click(submit);
    await waitFor(
      () => expect(screen.getByText(/message sent/i)).toBeInTheDocument(),
      {
        timeout: 5_000,
      },
    );
    expect(screen.getByText(/req-1/)).toBeInTheDocument();
  });

  it("shows a validation error when required fields are empty", async () => {
    installContactEndpoint();
    render(<ContactForm />);
    const submit = screen.getByRole("button", { name: /send message/i });
    await waitFor(() => expect(submit).toBeEnabled(), { timeout: 5_000 });
    // Token exists but the form fields are empty: client-side validation fires.
    fireEvent.click(submit);
    await waitFor(
      () =>
        expect(
          screen.getByText(/the message was not sent/i),
        ).toBeInTheDocument(),
      {
        timeout: 5_000,
      },
    );
  });

  it("shows the server error when the route fails", async () => {
    installContactEndpoint(502);
    render(<ContactForm />);
    fillForm();
    const submit = screen.getByRole("button", { name: /send message/i });
    await waitFor(() => expect(submit).toBeEnabled(), { timeout: 5_000 });
    fireEvent.click(submit);
    await waitFor(
      () => expect(screen.getByText(/could not be sent/i)).toBeInTheDocument(),
      { timeout: 5_000 },
    );
  });
});
