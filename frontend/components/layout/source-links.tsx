// "Source Code" and "License" links shown to every user of the web app (AGPL-3.0
// section 13: users interacting over a network are offered the source). URLs live in
// lib/project.ts.
import clsx from "clsx";
import { LICENSE_NAME, LICENSE_URL, SOURCE_CODE_URL } from "@/lib/project";

export function SourceLinks({ className }: { className?: string }) {
  return (
    <p className={clsx("flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400", className)} data-testid="source-links">
      <span>EvidenceX · {LICENSE_NAME}</span>
      <a href={SOURCE_CODE_URL} rel="noopener noreferrer" className="text-slate-300 underline-offset-2 hover:text-slate-50 hover:underline">
        Source Code
      </a>
      <a href={LICENSE_URL} rel="noopener noreferrer license" className="text-slate-300 underline-offset-2 hover:text-slate-50 hover:underline">
        License
      </a>
    </p>
  );
}
