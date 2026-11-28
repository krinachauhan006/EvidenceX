"use client";

import { useState } from "react";
import { Bot, Languages, Loader2, ShieldCheck, Trash2, UserPlus, Users } from "lucide-react";
import { addMember, changeMemberRole, listMembers, removeMember, setAiConsent } from "@/lib/api/auth";
import { aiStatus, ocrLanguages } from "@/lib/api/phase2";
import { hasRole, type Role } from "@/lib/types/case";
import { formatDateTime } from "@/lib/format";
import { useCaseContext } from "@/components/cases/case-shell";
import { useAuth } from "@/components/auth/auth-provider";
import {
  Badge,
  BUTTON,
  BUTTON_SOLID,
  Card,
  ErrorState,
  INPUT,
  SectionHeader,
  Skeleton,
} from "@/components/ui/primitives";
import { useToast } from "@/components/ui/toast";
import { errorText, useApi } from "@/hooks/use-api";

const ROLES: { id: Role; text: string }[] = [
  { id: "viewer", text: "Read everything, download reports and exports" },
  { id: "reviewer", text: "Viewer + review claims, events, inconsistencies; generate reports" },
  { id: "editor", text: "Reviewer + upload, process and analyse evidence" },
  { id: "owner", text: "Editor + manage members, AI consent, delete the case" },
];

export default function SettingsPage() {
  const { caseItem, role } = useCaseContext();
  return (
    <div className="space-y-6">
      <SectionHeader
        title="Members & settings"
        description="Who can see and change this case, and whether its extracted text may be sent to an AI service. Every change is recorded in the audit trail."
      />
      <MembersCard caseId={caseItem.id} isOwner={hasRole(role, "owner")} />
      <div className="grid gap-4 lg:grid-cols-2">
        <ConsentCard />
        <OcrCard />
      </div>
    </div>
  );
}

function MembersCard({ caseId, isOwner }: { caseId: string; isOwner: boolean }) {
  const { user } = useAuth();
  const notify = useToast();
  const members = useApi((signal) => listMembers(caseId, signal), [caseId], "Could not load members.");
  const [email, setEmail] = useState("");
  const [newRole, setNewRole] = useState<Role>("viewer");
  const [busy, setBusy] = useState<string | null>(null);

  async function run(key: string, fn: () => Promise<unknown>, ok: string) {
    setBusy(key);
    try {
      const res = (await fn()) as Awaited<ReturnType<typeof listMembers>>;
      members.setData(res);
      notify("success", ok);
      return true;
    } catch (err) {
      notify("error", "Not saved", errorText(err, "The change could not be saved."));
      return false;
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card className="p-5">
      <div className="flex items-center gap-2">
        <Users className="h-4 w-4 text-sky-300" aria-hidden />
        <h3 className="font-medium text-slate-100">Members</h3>
      </div>
      <p className="mt-1 text-xs text-slate-500">
        People without a membership cannot tell that this case exists. Access is checked by the server on every request.
      </p>
      {members.loading && !members.data && <Skeleton rows={2} className="mt-3" />}
      {members.error && <ErrorState message={members.error} onRetry={members.reload} />}
      {members.data && (
        <ul className="mt-3 divide-y divide-navy-800">
          {members.data.items.map((m) => (
            <li key={m.user_id} className="flex flex-wrap items-center justify-between gap-2 py-2.5">
              <div className="min-w-0">
                <p className="truncate text-sm text-slate-100">
                  {m.display_name} {m.user_id === user.id && <span className="text-xs text-slate-500">(you)</span>}
                </p>
                <p className="truncate text-xs text-slate-500">
                  {m.email} · added {formatDateTime(m.added_at)}
                </p>
              </div>
              {isOwner ? (
                <div className="flex items-center gap-1.5">
                  <select
                    value={m.role}
                    aria-label={`Role of ${m.display_name}`}
                    className={`${INPUT} w-auto py-1 text-xs`}
                    disabled={busy !== null}
                    onChange={(e) =>
                      void run(`role-${m.user_id}`, () => changeMemberRole(caseId, m.user_id, e.target.value as Role), `${m.display_name} is now ${e.target.value}`)
                    }
                  >
                    {ROLES.map((r) => (
                      <option key={r.id} value={r.id}>
                        {r.id}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className={`${BUTTON} border-failed/30 text-failed hover:bg-failed/10`}
                    disabled={busy !== null}
                    aria-label={`Remove ${m.display_name}`}
                    onClick={() => void run(`rm-${m.user_id}`, () => removeMember(caseId, m.user_id), `${m.display_name} removed`)}
                  >
                    <Trash2 className="h-3 w-3" aria-hidden />
                  </button>
                </div>
              ) : (
                <Badge>{m.role}</Badge>
              )}
            </li>
          ))}
        </ul>
      )}
      {isOwner && (
        <form
          className="mt-4 flex flex-col gap-2 border-t border-navy-800 pt-4 md:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            void run("add", () => addMember(caseId, email.trim(), newRole), `${email.trim()} added as ${newRole}`).then(
              (ok) => ok && setEmail(""),
            );
          }}
        >
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="colleague@example.org (must already have an account)"
            className={`${INPUT} flex-1 py-1.5`}
            aria-label="E-mail of the person to add"
            required
          />
          <select value={newRole} onChange={(e) => setNewRole(e.target.value as Role)} className={`${INPUT} w-auto py-1.5`} aria-label="Role">
            {ROLES.map((r) => (
              <option key={r.id} value={r.id}>
                {r.id}
              </option>
            ))}
          </select>
          <button type="submit" className={BUTTON_SOLID} disabled={busy !== null || !email.trim()}>
            {busy === "add" ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <UserPlus className="h-4 w-4" aria-hidden />}
            Add member
          </button>
        </form>
      )}
      <dl className="mt-4 grid gap-1.5 text-xs sm:grid-cols-2">
        {ROLES.map((r) => (
          <div key={r.id} className="rounded-md border border-navy-800 px-2.5 py-1.5">
            <dt className="font-medium text-slate-300">{r.id}</dt>
            <dd className="text-slate-500">{r.text}</dd>
          </div>
        ))}
      </dl>
    </Card>
  );
}

function ConsentCard() {
  const { caseItem, role, reloadCase } = useCaseContext();
  const notify = useToast();
  const status = useApi((signal) => aiStatus(signal), []);
  const [busy, setBusy] = useState(false);
  const isOwner = hasRole(role, "owner");
  const allowed = caseItem.ai_processing_allowed;

  async function toggle() {
    setBusy(true);
    try {
      await setAiConsent(caseItem.id, !allowed);
      reloadCase();
      notify("success", !allowed ? "AI processing allowed for this case" : "AI processing turned off for this case");
    } catch (err) {
      notify("error", "Consent not changed", errorText(err, ""));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card className="p-5">
      <div className="flex items-center gap-2">
        <Bot className="h-4 w-4 text-sky-300" aria-hidden />
        <h3 className="font-medium text-slate-100">AI processing</h3>
        <Badge tone={allowed ? "blue" : "neutral"}>{allowed ? "allowed" : "off"}</Badge>
      </div>
      <p className="mt-2 text-xs text-slate-400">
        When allowed and a key is configured, extracted text segments of this case (never file bytes, file names,
        other cases or account data) may be sent to {status.data?.provider ?? "the configured AI provider"} for claim
        extraction, grounded answers and report summaries. AI output is validated against a schema and labelled. With
        AI off, rule-based extraction and source-only answers are used.
      </p>
      {status.data && (
        <ul className="mt-3 space-y-1 text-xs text-slate-500">
          <li>Mode on this server: <span className="text-slate-300">{status.data.mode}</span></li>
          <li>Model: <span className="text-slate-300">{status.data.model}</span></li>
          <li>
            API key configured:{" "}
            <span className={status.data.key_configured ? "text-processed" : "text-slate-300"}>
              {status.data.key_configured ? "yes" : "no (AI cannot run even if allowed)"}
            </span>
          </li>
        </ul>
      )}
      {isOwner ? (
        <button
          type="button"
          role="switch"
          aria-checked={allowed}
          onClick={() => void toggle()}
          disabled={busy}
          className="mt-4 inline-flex items-center gap-3 text-sm text-slate-200"
        >
          <span className={`relative h-6 w-11 rounded-full border transition-colors ${allowed ? "border-sky-400 bg-sky-500/60" : "border-navy-600 bg-navy-800"}`}>
            <span className={`absolute top-0.5 w-[18px] rounded-full bg-white shadow transition-all ${allowed ? "left-[22px]" : "left-0.5"}`} style={{ height: 18 }} />
          </span>
          {busy ? "Saving…" : allowed ? "AI processing allowed" : "Allow AI processing"}
        </button>
      ) : (
        <p className="mt-4 flex items-center gap-1.5 text-xs text-slate-500">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> Only an owner can change this.
        </p>
      )}
    </Card>
  );
}

function OcrCard() {
  const langs = useApi((signal) => ocrLanguages(signal), [], "Could not read the OCR languages.");
  return (
    <Card className="p-5">
      <div className="flex items-center gap-2">
        <Languages className="h-4 w-4 text-sky-300" aria-hidden />
        <h3 className="font-medium text-slate-100">
          {langs.data && !langs.data.engine_available ? "OCR languages" : "OCR languages on this server"}
        </h3>
      </div>
      {langs.loading && !langs.data && <Skeleton rows={1} className="mt-3" />}
      {langs.error && <ErrorState message={langs.error} />}
      {langs.data && !langs.data.engine_available && (
        // This server has no OCR engine (e.g. a serverless deployment): OCR for images
        // and scanned PDFs is done by the separate local processing worker, whose
        // installed languages this server cannot list.
        <p className="mt-2 text-xs text-slate-500">
          OCR for images and scanned PDFs is handled by the local processing worker, using the
          language data installed on that computer.
        </p>
      )}
      {langs.data && langs.data.engine_available && (
        <>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {langs.data.installed.map((l) => (
              <Badge key={l.code} tone={l.usable_for_text ? "blue" : "neutral"} title={l.code}>
                {l.name}
              </Badge>
            ))}
          </div>
          <p className="mt-2 text-xs text-slate-500">
            Default: <span className="font-mono text-slate-300">{langs.data.default}</span> ·{" "}
            {langs.data.orientation_detection ? "page orientation is detected automatically" : "orientation detection unavailable"}.
            A different language can be chosen when processing an image or PDF.
          </p>
          <p className="mt-2 text-xs text-slate-500">{langs.data.install_help}</p>
        </>
      )}
    </Card>
  );
}
