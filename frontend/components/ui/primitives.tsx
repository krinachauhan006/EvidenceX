import clsx from "clsx";
import { AlertCircle, Inbox, Loader2 } from "lucide-react";
import type { Tone } from "@/components/analysis/review-labels";

// Small presentational building blocks shared by the investigation screens.
// Colour is semantic only: amber = potential inconsistency or pending review,
// green = verified/complete, red = errors, neutral slate otherwise.

const TONE_CLASSES: Record<Tone, string> = {
  neutral: "border-navy-600 bg-navy-800 text-slate-300",
  amber: "border-inconsistency/40 bg-inconsistency/10 text-inconsistency",
  green: "border-processed/40 bg-processed/10 text-processed",
  red: "border-failed/40 bg-failed/10 text-failed",
  blue: "border-sky-500/30 bg-sky-500/10 text-sky-300",
};

export function Badge({
  tone = "neutral",
  children,
  title,
  className,
}: {
  tone?: Tone;
  children: React.ReactNode;
  title?: string;
  className?: string;
}) {
  return (
    <span
      title={title}
      className={clsx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[11px] font-medium",
        TONE_CLASSES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}

export function Card({
  children,
  className,
  as: As = "section",
}: {
  children: React.ReactNode;
  className?: string;
  as?: "section" | "div" | "article" | "li";
}) {
  return (
    <As
      className={clsx(
        "rounded-xl border border-white/[0.06] bg-navy-900/70 shadow-[0_1px_0_0_rgba(255,255,255,0.03)_inset]",
        className,
      )}
    >
      {children}
    </As>
  );
}

export function SectionHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description?: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h2 className="text-lg font-semibold tracking-tight text-slate-100">{title}</h2>
        {description && <p className="mt-1 max-w-3xl text-sm text-slate-400">{description}</p>}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export function StatTile({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: Tone;
}) {
  return (
    <div className="rounded-lg border border-navy-800 bg-navy-900/70 px-4 py-3">
      <p className="text-[11px] font-medium uppercase tracking-wider text-slate-500">{label}</p>
      <p
        className={clsx(
          "mt-1 text-2xl font-semibold tabular-nums",
          tone === "amber"
            ? "text-inconsistency"
            : tone === "green"
              ? "text-processed"
              : tone === "red"
                ? "text-failed"
                : "text-slate-100",
        )}
      >
        {value}
      </p>
      {hint && <p className="mt-0.5 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="py-6">
      <p className="flex items-center gap-2 text-sm text-slate-400">
        <Loader2 className="h-4 w-4 animate-spin text-sky-400" aria-hidden /> {label}
      </p>
      <div className="mt-3 h-0.5 max-w-xs overflow-hidden rounded bg-navy-800" aria-hidden>
        <div className="evx-indeterminate h-full w-2/5 rounded bg-gradient-to-r from-transparent via-sky-400/70 to-transparent" />
      </div>
    </div>
  );
}

/** Placeholder blocks shown while a list loads. */
export function Skeleton({ rows = 3, className }: { rows?: number; className?: string }) {
  return (
    <div className={clsx("space-y-2", className)} aria-hidden>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="evx-skeleton h-14 rounded-lg border border-navy-800" />
      ))}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-md border border-failed/30 bg-failed/10 px-3 py-2 text-sm text-failed"
    >
      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <span>
        {message}{" "}
        {onRetry && (
          <button type="button" onClick={onRetry} className="underline underline-offset-2">
            Try again
          </button>
        )}
      </span>
    </div>
  );
}

export function EmptyState({
  title,
  children,
  icon,
}: {
  title: string;
  children?: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div className="relative flex flex-col items-center overflow-hidden rounded-xl border border-dashed border-navy-700 px-6 py-12 text-center">
      <div aria-hidden className="evx-grid-bg pointer-events-none absolute inset-0" />
      <div className="relative flex h-12 w-12 items-center justify-center rounded-full border border-navy-700 bg-navy-900 text-slate-500 shadow-[0_0_0_6px_rgba(23,35,56,0.5)]">
        {icon ?? <Inbox className="h-5 w-5" aria-hidden />}
      </div>
      <p className="relative mt-3 text-sm font-medium text-slate-200">{title}</p>
      {children && <div className="relative mt-1 max-w-md text-sm text-slate-500">{children}</div>}
    </div>
  );
}

/** A small "?" affordance that explains a term on hover or keyboard focus. */
export function InfoTip({ text, label = "What does this mean?" }: { text: string; label?: string }) {
  return (
    <span className="group relative inline-flex align-middle">
      <button
        type="button"
        aria-label={`${label} ${text}`}
        className="inline-flex h-4 w-4 items-center justify-center rounded-full border border-navy-600 text-[10px] text-slate-400 hover:text-slate-100"
      >
        ?
      </button>
      {/* display:none until hovered/focused: an invisible-but-laid-out tooltip near the
          right edge widened the page on narrow screens. Aligned to the trigger's right
          edge and width-capped so an open tooltip stays on screen. */}
      <span
        role="tooltip"
        className="pointer-events-none absolute bottom-full right-0 z-30 mb-2 hidden w-64 max-w-[min(16rem,80vw)] rounded-md border border-navy-700 bg-navy-950 px-2.5 py-2 text-left text-[11px] font-normal normal-case leading-relaxed tracking-normal text-slate-300 shadow-xl group-hover:block group-focus-within:block"
      >
        {text}
      </span>
    </span>
  );
}

export const BUTTON =
  "inline-flex items-center gap-1.5 rounded-md border border-navy-700 px-3 py-1.5 text-xs font-medium text-slate-200 hover:bg-navy-800 disabled:cursor-not-allowed disabled:opacity-50";
export const BUTTON_PRIMARY =
  "inline-flex items-center gap-1.5 rounded-md border border-sky-400/40 bg-sky-500/15 px-3 py-1.5 text-xs font-medium text-sky-100 hover:bg-sky-500/25 disabled:cursor-not-allowed disabled:opacity-50";
export const BUTTON_SOLID =
  "inline-flex items-center justify-center gap-1.5 rounded-md bg-sky-500 px-3.5 py-2 text-sm font-semibold text-navy-950 shadow-[0_0_24px_-6px_rgba(56,189,248,0.6)] hover:bg-sky-400 disabled:cursor-not-allowed disabled:opacity-50";
export const INPUT =
  "w-full rounded-md border border-navy-700 bg-navy-950 px-2.5 py-1.5 text-sm text-slate-100 placeholder:text-slate-600 focus:border-navy-600 focus:outline-none focus:ring-1 focus:ring-navy-600";

/**
 * Horizontal tab bar. Scrolls sideways when the tabs do not fit (with a scrollbar only
 * when actually needed), never vertically. The baseline is an inset shadow so the
 * active tab's 2px underline sits on it without the tabs overhanging the container,
 * which is what produced a 1px vertical overflow and a scrollbar stub.
 */
export const TAB_BAR =
  "flex gap-1 overflow-x-auto overflow-y-hidden shadow-[inset_0_-1px_0_0_#172338]";
export const TAB_ITEM = "shrink-0 whitespace-nowrap border-b-2 px-3 py-2 text-sm";

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
  label,
}: {
  tabs: { id: T; label: string; count?: number }[];
  active: T;
  onChange: (id: T) => void;
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className={TAB_BAR}>
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          type="button"
          aria-selected={t.id === active}
          onClick={() => onChange(t.id)}
          className={clsx(
            TAB_ITEM,
            t.id === active
              ? "border-slate-200 text-slate-100"
              : "border-transparent text-slate-400 hover:text-slate-200",
          )}
        >
          {t.label}
          {t.count !== undefined && (
            <span className="ml-1.5 rounded bg-navy-800 px-1.5 py-0.5 text-[11px] tabular-nums text-slate-400">
              {t.count}
            </span>
          )}
        </button>
      ))}
    </div>
  );
}
