import { useId } from "react";
import Link from "next/link";
import clsx from "clsx";

/** The EvidenceX mark: linked nodes inside a lens. Pure SVG, no external asset. */
export function BrandMark({ className }: { className?: string }) {
  const id = `evx-g${useId().replace(/:/g, "")}`;
  return (
    <svg viewBox="0 0 32 32" className={clsx("h-7 w-7", className)} aria-hidden>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#38bdf8" />
          <stop offset="1" stopColor="#6366f1" />
        </linearGradient>
      </defs>
      <circle cx="14" cy="14" r="10.5" fill="none" stroke={`url(#${id})`} strokeWidth="2.2" />
      <path d="M21.5 21.5 L28 28" stroke={`url(#${id})`} strokeWidth="2.6" strokeLinecap="round" />
      <path d="M9.5 16.5 L14 10 L18.5 16.5 Z" fill="none" stroke="#cbd5e1" strokeWidth="1.2" />
      <circle cx="9.5" cy="16.5" r="1.9" fill="#e2e8f0" />
      <circle cx="14" cy="10" r="1.9" fill="#38bdf8" />
      <circle cx="18.5" cy="16.5" r="1.9" fill="#f59e0b" />
    </svg>
  );
}

export function Brand({ href = "/", className }: { href?: string; className?: string }) {
  return (
    <Link href={href} className={clsx("flex items-center gap-2", className)}>
      <BrandMark />
      <span className="text-[17px] font-semibold tracking-tight text-slate-50">
        Evidence<span className="text-sky-400">X</span>
      </span>
    </Link>
  );
}
