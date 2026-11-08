import type { ReactNode } from "react";

export type StatusBannerTone = "info" | "warning" | "danger" | "success";

export interface StatusBannerProps {
  readonly tone: StatusBannerTone;
  readonly title: string;
  readonly description: string;
  readonly children?: ReactNode;
}

const TONE_CLASSES: Record<StatusBannerTone, string> = {
  info: "border-sky-300 bg-sky-50 text-sky-950",
  warning: "border-amber-300 bg-amber-50 text-amber-950",
  danger: "border-rose-300 bg-rose-50 text-rose-950",
  success: "border-emerald-300 bg-emerald-50 text-emerald-950",
};

export function StatusBanner({
  tone,
  title,
  description,
  children,
}: StatusBannerProps) {
  return (
    <section
      aria-label={title}
      className={`rounded-lg border px-4 py-3 ${TONE_CLASSES[tone]}`}
    >
      <p className="text-sm font-semibold">{title}</p>
      <p className="mt-1 text-sm">{description}</p>
      {children === undefined ? null : (
        <div className="mt-2 text-sm">{children}</div>
      )}
    </section>
  );
}
