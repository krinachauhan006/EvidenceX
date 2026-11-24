import clsx from "clsx";
import type { CaseStatus } from "@/lib/types/case";

// Color semantics follow the design language. "open" uses neutral styling
// (unresolved); "archived" is muted. Amber/green are reserved for
// inconsistencies and completed processing in later stages.
export function StatusBadge({ status }: { status: CaseStatus }) {
  return (
    <span
      className={clsx(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        status === "open" && "bg-navy-700 text-unresolved",
        status === "archived" && "bg-charcoal-800 text-slate-500",
      )}
    >
      {status}
    </span>
  );
}
