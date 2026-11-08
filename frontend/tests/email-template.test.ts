import { describe, expect, it } from "vitest";

import {
  escapeHtml,
  renderContactEmail,
} from "@/features/contact/email-template";

describe("renderContactEmail", () => {
  it("escapes user content so no markup can be injected", () => {
    const html = renderContactEmail({
      name: '<script>alert("x")</script>',
      email: "ada@example.org",
      subject: "Hi <b>there</b>",
      message: "line1\nline2 <img src=x onerror=alert(1)>",
      requestId: "req-1",
      receivedAt: "2026-11-08T10:00:00Z",
    });
    expect(html).not.toContain("<script>");
    expect(html).not.toContain("<img");
    expect(html).not.toContain("<b>there</b>");
    expect(html).toContain("&lt;script&gt;");
    expect(html).toContain("line1<br />line2");
  });

  it("escapeHtml covers all five HTML special characters", () => {
    expect(escapeHtml(`<a href="x">&'</a>`)).toBe(
      "&lt;a href=&quot;x&quot;&gt;&amp;&#39;&lt;/a&gt;",
    );
  });
});
