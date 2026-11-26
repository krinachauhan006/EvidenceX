"use client";

import { useState } from "react";
import Link from "next/link";
import clsx from "clsx";
import { BookOpenText, Bot, FileSearch, Link2, Loader2, MessageSquareText, Search, Sparkles } from "lucide-react";
import { aiStatus, askCase, searchCase } from "@/lib/api/phase2";
import type { AskResult, SearchHit, SearchResult } from "@/lib/types/phase2";
import { useCaseContext } from "@/components/cases/case-shell";
import { sourceHref } from "@/components/analysis/source-link";
import { sourceLabel } from "@/components/analysis/claim-card";
import {
  Badge,
  BUTTON,
  BUTTON_SOLID,
  Card,
  EmptyState,
  ErrorState,
  InfoTip,
  INPUT,
  SectionHeader,
  Skeleton,
  Tabs,
} from "@/components/ui/primitives";
import { errorText, useApi } from "@/hooks/use-api";

const KINDS = [
  { id: "segment", label: "Source text" },
  { id: "claim", label: "Claims" },
  { id: "entity", label: "Entities" },
  { id: "event", label: "Events" },
] as const;

const EXAMPLES = ["truck arrival", "invoice payment", "witness statement", "delay"];

export default function SearchPage() {
  const [mode, setMode] = useState<"search" | "ask">("search");
  return (
    <div>
      <SectionHeader
        title="Search & ask"
        description="Find any passage, claim, entity or event in this case, or ask a question answered only from cited sources."
      />
      <Tabs<"search" | "ask">
        label="Mode"
        active={mode}
        onChange={setMode}
        tabs={[
          { id: "search", label: "Search the case" },
          { id: "ask", label: "Ask a question" },
        ]}
      />
      <div className="mt-5">{mode === "search" ? <SearchPanel /> : <AskPanel />}</div>
    </div>
  );
}

function SearchPanel() {
  const { caseItem } = useCaseContext();
  const caseId = caseItem.id;
  const [q, setQ] = useState("");
  const [kinds, setKinds] = useState<string[]>([]);
  const [result, setResult] = useState<SearchResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run(query = q) {
    if (!query.trim()) return;
    setQ(query);
    setBusy(true);
    setError(null);
    try {
      setResult(await searchCase(caseId, query.trim(), { kinds, limit: 50 }));
    } catch (err) {
      setError(errorText(err, "The search failed."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void run();
        }}
        className="flex flex-col gap-2 md:flex-row"
        role="search"
      >
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-2.5 h-4 w-4 text-slate-500" aria-hidden />
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search words, ids, names… e.g. KX-4471, arrival, invoice"
            maxLength={300}
            className={`${INPUT} py-2 pl-9 text-sm`}
            aria-label="Search this case"
          />
        </div>
        <button type="submit" className={BUTTON_SOLID} disabled={busy || !q.trim()}>
          {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Search className="h-4 w-4" aria-hidden />}
          Search
        </button>
      </form>
      <div className="flex flex-wrap items-center gap-1.5 text-xs">
        <span className="text-slate-500">Look in:</span>
        {KINDS.map((k) => {
          const on = kinds.includes(k.id);
          return (
            <button
              key={k.id}
              type="button"
              aria-pressed={on}
              onClick={() => setKinds((all) => (on ? all.filter((x) => x !== k.id) : [...all, k.id]))}
              className={clsx(
                "rounded-full border px-2.5 py-0.5 transition-colors",
                on ? "border-sky-400/60 bg-sky-500/15 text-sky-200" : "border-navy-700 text-slate-400 hover:text-slate-200",
              )}
            >
              {k.label}
            </button>
          );
        })}
        <span className="text-slate-600">{kinds.length === 0 ? "(everything)" : ""}</span>
      </div>

      {error && <ErrorState message={error} />}
      {busy && !result && <Skeleton rows={4} />}
      {!result && !busy && (
        <EmptyState title="Search across every source in this case" icon={<FileSearch className="h-5 w-5" aria-hidden />}>
          <span className="block">Try:</span>
          <span className="mt-2 flex flex-wrap justify-center gap-1.5">
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" className={BUTTON} onClick={() => void run(ex)}>
                {ex}
              </button>
            ))}
          </span>
        </EmptyState>
      )}
      {result && (
        <div className={clsx("space-y-3", busy && "opacity-60")}>
          <p className="flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
            {result.total} result{result.total === 1 ? "" : "s"} for “{result.query}”
            <InfoTip text={`${result.method}: keyword ranking (BM25) with stemming, a small synonym list and typo tolerance. It is not embedding-based and uses no external service.`} />
            {result.expanded_terms.length > 0 && (
              <span>· also matched: {result.expanded_terms.slice(0, 10).join(", ")}</span>
            )}
          </p>
          {result.items.length === 0 && <EmptyState title="No matches">Try other words or remove filters.</EmptyState>}
          <ul className="space-y-2">
            {result.items.map((h) => (
              <Hit key={`${h.kind}-${h.id}`} caseId={caseId} hit={h} terms={result.expanded_terms} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** Wraps query terms (and their stems) in <mark>; text is never changed otherwise. */
function Highlighted({ text, terms }: { text: string; terms: string[] }) {
  const usable = terms.filter((t) => t.length >= 3).map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (usable.length === 0) return <>{text}</>;
  const rx = new RegExp(`(${usable.join("|")})`, "gi");
  return (
    <>
      {text.split(rx).map((part, i) =>
        i % 2 === 1 ? (
          <mark key={i} className="rounded bg-sky-400/20 px-0.5 text-sky-100">
            {part}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

function Hit({ caseId, hit, terms }: { caseId: string; hit: SearchHit; terms: string[] }) {
  const root = `/cases/${caseId}`;
  const href =
    hit.kind === "entity"
      ? `${root}/entities?focus=${hit.id}`
      : hit.kind === "event"
        ? `${root}/events`
        : hit.evidence_id
          ? sourceHref(caseId, { evidenceId: hit.evidence_id, segmentId: hit.segment_id, claimId: hit.claim_id, locator: hit.locator })
          : null;
  return (
    <li>
      <Card className="evx-card-hover p-3 hover:border-sky-500/30">
        <div className="flex flex-wrap items-center gap-1.5 text-xs">
          <Badge tone={hit.kind === "claim" ? "blue" : hit.kind === "event" ? "green" : "neutral"}>{hit.kind}</Badge>
          <span className="font-medium text-slate-200">{hit.title}</span>
          {hit.evidence_name && (
            <span className="text-slate-500">
              {hit.evidence_name}
              {hit.locator ? ` · ${sourceLabel(hit.locator)}` : ""}
            </span>
          )}
          {hit.review_status && <Badge>{hit.review_status.replace(/_/g, " ")}</Badge>}
        </div>
        <p className="mt-1.5 whitespace-pre-wrap break-words font-mono text-[13px] text-slate-300">
          <Highlighted text={hit.excerpt} terms={terms} />
        </p>
        <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
          <p className="text-[11px] text-slate-500">{hit.why}</p>
          {href && (
            <Link href={href} className={BUTTON}>
              <Link2 className="h-3 w-3" aria-hidden /> {hit.kind === "segment" || hit.kind === "claim" ? "Open source" : "Open"}
            </Link>
          )}
        </div>
      </Card>
    </li>
  );
}

function AskPanel() {
  const { caseItem } = useCaseContext();
  const caseId = caseItem.id;
  const status = useApi((signal) => aiStatus(signal), []);
  const [question, setQuestion] = useState("");
  const [result, setResult] = useState<AskResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const aiOn = Boolean(status.data?.available && caseItem.ai_processing_allowed);

  async function ask() {
    if (question.trim().length < 3) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await askCase(caseId, question.trim()));
    } catch (err) {
      setError(errorText(err, "The question could not be answered."));
    } finally {
      setBusy(false);
    }
  }

  const byRef = new Map(result?.citations.map((c) => [c.ref, c]) ?? []);
  return (
    <div className="space-y-4">
      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2 text-xs">
          {aiOn ? (
            <Badge tone="blue">
              <Bot className="h-3 w-3" aria-hidden /> AI answers with citations ({status.data?.model})
            </Badge>
          ) : (
            <Badge>
              <BookOpenText className="h-3 w-3" aria-hidden /> Source passages only (no AI)
            </Badge>
          )}
          <span className="text-slate-500">
            {aiOn
              ? "Statements without a valid citation are removed before you see them."
              : !status.data?.key_configured
                ? "No AI key is configured on this server, so the most relevant passages are shown verbatim."
                : "The case owner has not allowed AI processing, so the most relevant passages are shown verbatim."}
          </span>
        </div>
        <form
          className="mt-3 flex flex-col gap-2 md:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            void ask();
          }}
        >
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            maxLength={500}
            placeholder="e.g. When did the truck arrive at Warehouse A?"
            className={`${INPUT} flex-1 py-2 text-sm`}
            aria-label="Question about this case"
          />
          <button type="submit" className={BUTTON_SOLID} disabled={busy || question.trim().length < 3}>
            {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Sparkles className="h-4 w-4" aria-hidden />}
            Ask
          </button>
        </form>
      </Card>

      {error && <ErrorState message={error} />}
      {busy && <Skeleton rows={2} />}
      {!result && !busy && (
        <EmptyState title="Answers cite their sources" icon={<MessageSquareText className="h-5 w-5" aria-hidden />}>
          Every statement links to the exact passage it comes from. EvidenceX does not judge who is right.
        </EmptyState>
      )}
      {result && !busy && (
        <div className="evx-page space-y-3">
          <ul className="space-y-2">
            {result.answer.map((s, i) => (
              <li key={i} className="rounded-xl border border-white/[0.06] bg-navy-900/70 p-3 text-sm text-slate-200">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <p className="min-w-0 flex-1 whitespace-pre-wrap break-words">{s.text}</p>
                  <Badge tone={s.support === "supported" ? "green" : s.support === "interpretation" ? "amber" : "neutral"}>
                    {s.support}
                  </Badge>
                </div>
                <p className="mt-1.5 flex flex-wrap gap-1">
                  {s.citations.map((r) => {
                    const c = byRef.get(r);
                    return (
                      <a key={r} href={`#cite-${r}`} className="rounded border border-sky-500/30 px-1.5 text-[11px] text-sky-300 hover:bg-sky-500/10">
                        [{r}] {c?.evidence_name ?? ""}
                      </a>
                    );
                  })}
                </p>
              </li>
            ))}
          </ul>
          {result.removed_unsupported > 0 && (
            <p className="text-xs text-slate-500">
              {result.removed_unsupported} statement(s) were removed because they had no valid citation.
            </p>
          )}
          <p className="text-xs text-slate-500">{result.notice}</p>
          <Card className="p-3">
            <p className="text-xs font-medium uppercase tracking-wider text-slate-500">Cited sources</p>
            <ol className="mt-2 space-y-2">
              {result.citations.map((c) => (
                <li key={c.ref} id={`cite-${c.ref}`} className="rounded-lg border border-navy-800 bg-navy-950/60 p-2.5 text-xs">
                  <p className="text-slate-400">
                    <span className="font-mono text-sky-300">[{c.ref}]</span> {c.evidence_name ?? c.kind}
                    {c.locator ? ` · ${sourceLabel(c.locator)}` : ""}
                  </p>
                  <p className="mt-1 whitespace-pre-wrap break-words font-mono text-[12px] text-slate-200">{c.excerpt}</p>
                </li>
              ))}
            </ol>
          </Card>
        </div>
      )}
    </div>
  );
}
