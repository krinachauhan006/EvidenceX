import Link from "next/link";
import { FileSearch, FolderOpen } from "lucide-react";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen">
      {/* Left rail — foundation for the future evidence library panel. */}
      <aside className="w-60 shrink-0 border-r border-navy-800 bg-navy-900 p-4">
        <div className="mb-8 flex items-center gap-2">
          <FileSearch className="h-6 w-6 text-processed" aria-hidden />
          <span className="text-lg font-semibold tracking-tight text-slate-100">
            EvidenceX
          </span>
        </div>
        <nav className="space-y-1">
          <Link
            href="/cases"
            className="flex items-center gap-2 rounded-md px-3 py-2 text-sm text-slate-300 hover:bg-navy-800 hover:text-slate-100"
          >
            <FolderOpen className="h-4 w-4" aria-hidden />
            Cases
          </Link>
        </nav>
        <p className="mt-8 text-xs leading-relaxed text-slate-500">
          Investigation workspace. EvidenceX surfaces and organizes evidence; it
          does not determine guilt, detect deception, or authenticate evidence.
        </p>
      </aside>

      {/* min-w-0: a flex child defaults to min-width:auto and would otherwise grow to
          its widest content (long quotes, badge rows), overflowing narrow screens. */}
      <main className="min-w-0 flex-1 bg-navy-950">
        <div className="mx-auto max-w-7xl px-4 py-8 md:px-8">{children}</div>
      </main>
    </div>
  );
}
