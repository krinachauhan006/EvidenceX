"use client";

import { useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import { BookOpen, FolderKanban, LogOut, Menu, ShieldCheck, X } from "lucide-react";
import { AuthGate, useAuth } from "@/components/auth/auth-provider";
import { Brand } from "@/components/layout/brand";
import { SourceLinks } from "@/components/layout/source-links";
import { ToastProvider } from "@/components/ui/toast";

const NAV = [
  { href: "/cases", label: "Investigations", icon: FolderKanban },
  { href: "/#how-it-works", label: "How it works", icon: BookOpen },
];

/** Signed-in layout: a fixed sidebar on wide screens, a top bar with a drawer below md. */
export function AppShell({ children }: { children: React.ReactNode }) {
  return (
    <AuthGate>
      <ToastProvider>
        <Frame>{children}</Frame>
      </ToastProvider>
    </AuthGate>
  );
}

function Frame({ children }: { children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-screen bg-navy-950">
      <aside className="sticky top-0 hidden h-screen w-64 shrink-0 flex-col border-r border-white/5 bg-navy-900/80 backdrop-blur md:flex">
        <Sidebar />
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <button
            type="button"
            className="absolute inset-0 bg-black/60"
            aria-label="Close navigation"
            onClick={() => setOpen(false)}
          />
          <aside className="relative flex h-full w-72 flex-col border-r border-white/5 bg-navy-900">
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex items-center justify-between border-b border-white/5 bg-navy-950/85 px-4 py-3 backdrop-blur md:hidden">
          <Brand href="/cases" />
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="rounded-md border border-navy-700 p-1.5 text-slate-300"
            aria-label="Open navigation"
          >
            <Menu className="h-5 w-5" aria-hidden />
          </button>
        </header>
        {/* min-w-0: a flex child defaults to min-width:auto and would otherwise grow to
            its widest content (long quotes, badge rows), overflowing narrow screens. */}
        <main className="min-w-0 flex-1">
          <div className="mx-auto max-w-7xl px-4 py-6 md:px-8 md:py-8">{children}</div>
        </main>
        {/* Shown on every signed-in page and every screen size (the sidebar is hidden
            on small screens), so the source offer is always one click away. */}
        <footer className="border-t border-white/5 px-4 py-4 md:px-8">
          <SourceLinks className="mx-auto max-w-7xl" />
        </footer>
      </div>
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { user, signOut } = useAuth();
  return (
    <>
      <div className="flex items-center justify-between px-5 pb-6 pt-5">
        <Brand href="/cases" />
        {onNavigate && (
          <button type="button" onClick={onNavigate} aria-label="Close navigation" className="text-slate-400">
            <X className="h-5 w-5" aria-hidden />
          </button>
        )}
      </div>
      <nav className="space-y-0.5 px-3" aria-label="Main">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/cases" ? pathname.startsWith("/cases") : false;
          return (
            <Link
              key={href}
              href={href}
              onClick={onNavigate}
              aria-current={active ? "page" : undefined}
              className={clsx(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors",
                active
                  ? "bg-white/[0.06] text-slate-50 shadow-[inset_2px_0_0_0_#38bdf8]"
                  : "text-slate-400 hover:bg-white/[0.04] hover:text-slate-100",
              )}
            >
              <Icon className="h-4 w-4" aria-hidden />
              {label}
            </Link>
          );
        })}
      </nav>

      <div className="mx-5 mt-8 rounded-lg border border-white/5 bg-white/[0.02] p-3 text-[11px] leading-relaxed text-slate-500">
        <p className="mb-1 flex items-center gap-1.5 font-medium text-slate-400">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> Analytical aid
        </p>
        EvidenceX organizes evidence and surfaces possible inconsistencies for human review. It
        does not determine guilt, detect deception or authenticate evidence.
      </div>

      <div className="mt-auto border-t border-white/5 p-4">
        <p className="truncate text-sm font-medium text-slate-200" title={user.display_name}>
          {user.display_name}
        </p>
        <p className="truncate text-xs text-slate-500" title={user.email}>
          {user.email}
        </p>
        <button
          type="button"
          onClick={() => void signOut()}
          className="mt-3 inline-flex items-center gap-1.5 rounded-md border border-navy-700 px-2.5 py-1 text-xs text-slate-300 hover:bg-navy-800"
        >
          <LogOut className="h-3.5 w-3.5" aria-hidden /> Sign out
        </button>
      </div>
    </>
  );
}
