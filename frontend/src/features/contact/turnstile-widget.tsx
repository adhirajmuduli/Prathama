"use client";

/**
 * The Cloudflare Turnstile widget.
 *
 * The official script is loaded exactly once; the widget renders explicitly
 * into a container, and the token is only ever produced after the
 * server-side Siteverify call accepts it. Expired and errored tokens are
 * surfaced accessibly and the widget is reset so the user can retry.
 */

import { useCallback, useEffect, useRef, useState } from "react";

const TURNSTILE_SCRIPT_URL =
  "https://challenges.cloudflare.com/turnstile/v0/api.js";
const SCRIPT_ID = "trendsmapp-turnstile-script";

interface TurnstileApi {
  render: (
    container: HTMLElement,
    options: {
      sitekey: string;
      callback: (token: string) => void;
      "expired-callback": () => void;
      "error-callback": () => void;
      theme?: "light" | "dark" | "auto";
    },
  ) => string;
  remove: (widgetId: string) => void;
  reset: (widgetId: string) => void;
}

declare global {
  interface Window {
    turnstile?: TurnstileApi;
  }
}

let scriptPromise: Promise<void> | null = null;

function loadTurnstileScript(): Promise<void> {
  if (typeof window === "undefined") {
    return Promise.reject(new Error("Turnstile needs a browser."));
  }
  if (window.turnstile !== undefined) {
    return Promise.resolve();
  }
  if (scriptPromise === null) {
    scriptPromise = new Promise((resolve, reject) => {
      const existing = document.getElementById(SCRIPT_ID);
      if (existing !== null) {
        existing.addEventListener("load", () => resolve());
        existing.addEventListener("error", () =>
          reject(new Error("Turnstile failed to load.")),
        );
        return;
      }
      const script = document.createElement("script");
      script.id = SCRIPT_ID;
      script.src = `${TURNSTILE_SCRIPT_URL}?render=explicit`;
      script.async = true;
      script.defer = true;
      script.addEventListener("load", () => resolve());
      script.addEventListener("error", () =>
        reject(new Error("Turnstile failed to load.")),
      );
      document.head.appendChild(script);
    });
  }
  return scriptPromise;
}

export interface TurnstileWidgetProps {
  readonly siteKey: string;
  readonly onVerify: (token: string) => void;
  readonly onExpire: () => void;
  readonly onError: () => void;
}

export function TurnstileWidget({
  siteKey,
  onVerify,
  onExpire,
  onError,
}: TurnstileWidgetProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const widgetIdRef = useRef<string | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "failed">(
    "loading",
  );

  const renderWidget = useCallback(() => {
    if (containerRef.current === null || window.turnstile === undefined) {
      return false;
    }
    widgetIdRef.current = window.turnstile.render(containerRef.current, {
      sitekey: siteKey,
      callback: (token) => {
        setStatus("ready");
        onVerify(token);
      },
      "expired-callback": () => {
        onExpire();
      },
      "error-callback": () => {
        setStatus("failed");
        onError();
      },
      theme: "auto",
    });
    setStatus("ready");
    return true;
  }, [siteKey, onVerify, onExpire, onError]);

  useEffect(() => {
    let cancelled = false;
    const mount = async () => {
      try {
        await loadTurnstileScript();
        if (!cancelled) {
          renderWidget();
        }
      } catch {
        if (!cancelled) {
          setStatus("failed");
          onError();
        }
      }
    };
    void mount();
    return () => {
      cancelled = true;
      if (widgetIdRef.current !== null && window.turnstile !== undefined) {
        window.turnstile.remove(widgetIdRef.current);
        widgetIdRef.current = null;
      }
    };
  }, [renderWidget, onError]);

  const retry = useCallback(() => {
    setStatus("loading");
    if (widgetIdRef.current !== null && window.turnstile !== undefined) {
      window.turnstile.reset(widgetIdRef.current);
      return;
    }
    const again = async () => {
      try {
        await loadTurnstileScript();
        renderWidget();
      } catch {
        setStatus("failed");
        onError();
      }
    };
    void again();
  }, [renderWidget, onError]);

  return (
    <div className="space-y-2">
      <div ref={containerRef} data-testid="turnstile-container" />
      {status === "loading" ? (
        <p className="text-xs text-slate-500" role="status">
          Loading the human check…
        </p>
      ) : null}
      {status === "failed" ? (
        <div className="flex items-center gap-3">
          <p role="alert" className="text-xs text-rose-700">
            The human check could not be completed.
          </p>
          <button
            type="button"
            onClick={retry}
            className="rounded border border-slate-300 px-2 py-1 text-xs font-medium text-slate-700 hover:bg-slate-50"
          >
            Retry
          </button>
        </div>
      ) : null}
    </div>
  );
}
