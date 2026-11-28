import type { Metadata } from "next";
import Link from "next/link";
import {
  AudioLines,
  Ban,
  Bot,
  Check,
  Clapperboard,
  FileSpreadsheet,
  FileText,
  Fingerprint,
  Image as ImageIcon,
  KeyRound,
  Layers,
  Lock,
  Mail,
  Scale,
  ShieldCheck,
  Sparkles,
  Users,
} from "lucide-react";
import { HeroVisual } from "@/components/landing/hero-visual";
import {
  EventDemo,
  GraphDemo,
  LandingNav,
  PipelineStepper,
  PrimaryCta,
  ProvenanceDemo,
  TrustBadge,
} from "@/components/landing/interactive";
import { FramedPhoto, SectionPhoto } from "@/components/landing/photo";
import { Brand } from "@/components/layout/brand";
import { LICENSE_NAME, LICENSE_URL, SOURCE_CODE_URL } from "@/lib/project";

export const metadata: Metadata = {
  title: "EvidenceX · Evidence doesn't exist in isolation",
  description:
    "Connect documents, images, audio, video, e-mail and spreadsheets in one source-anchored investigation workspace. Every claim links to its exact source; people make every decision.",
};

const FORMATS = [
  { icon: FileText, name: "PDF documents", anchor: "page + bounding box", note: "embedded text, or OCR for scanned pages" },
  { icon: ImageIcon, name: "Images", anchor: "pixel region on the original", note: "OCR with orientation and deskew" },
  { icon: AudioLines, name: "Audio", anchor: "start–end timestamp, word timing", note: "local speech recognition" },
  { icon: Clapperboard, name: "Video", anchor: "frame time + text region", note: "sampled frames, OCR and soundtrack" },
  { icon: Mail, name: "E-mail (.eml)", anchor: "header name or message part", note: "headers, bodies, attachment list" },
  { icon: FileSpreadsheet, name: "CSV & XLSX", anchor: "row + column, sheet + cell", note: "formulas shown, never run" },
];

const DOES = [
  "Extracts statements that quote their source verbatim and link to the exact location",
  "Proposes which accounts may describe one event, and explains why",
  "Surfaces possible inconsistencies with benign alternative explanations",
  "Keeps dates and times at the precision the source gives",
  "Records every human decision in a tamper-evident audit trail",
];

const DOES_NOT = [
  "Determine guilt or innocence",
  "Detect lies or deception",
  "Authenticate evidence or certify it as genuine",
  "Present confidence as a calibrated probability of truth",
  "Merge records or confirm findings without a person",
];

// Shared type scale: eyebrow → heading → body. Body copy is slate-300 on the dark
// surfaces (≈ 12:1); secondary copy slate-400 (≈ 7.5:1). Nothing is faded with opacity.
const EYEBROW = "text-xs font-semibold uppercase tracking-[0.25em] text-sky-300";
const H2 = "text-3xl font-semibold tracking-tight text-slate-50 md:text-4xl md:leading-[1.15]";
const LEAD = "text-base leading-relaxed text-slate-300 md:text-lg";
const CARD = "evx-card-hover rounded-xl border border-white/[0.08] bg-navy-900/80 backdrop-blur-sm";

function SectionTitle({ eyebrow, title, children }: { eyebrow: string; title: string; children?: React.ReactNode }) {
  return (
    <div className="mx-auto mb-12 max-w-2xl text-center">
      <p className={EYEBROW}>{eyebrow}</p>
      <h2 className={`mt-3 ${H2}`}>{title}</h2>
      {children && <p className={`mt-4 ${LEAD}`}>{children}</p>}
    </div>
  );
}

export default function LandingPage() {
  return (
    // overflow-x-CLIP (not hidden): "hidden" would make this wrapper a scroll
    // container and stop the sticky header from sticking to the viewport.
    <div className="relative min-h-screen overflow-x-clip bg-navy-950">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:rounded focus:bg-sky-500 focus:px-3 focus:py-2 focus:text-navy-950">
        Skip to content
      </a>
      <LandingNav />

      <main id="main" className="relative">
        {/* A. Hero — investigator's desk at night behind the product illustration */}
        <section className="relative isolate -mt-16 pt-16" data-section="hero">
          {/* Photograph of a desk at night (never masked). The opaque case panel sits
              above it; lamp light and screen glow frame the panel. Overlay: darkest
              behind the headline. Stacked layouts get an even overlay so the
              full-width text stays readable. The CSS desk artwork is the fallback. */}
          <SectionPhoto
            name="desk"
            position="50% 50%"
            fallback="desk"
            priority
            overlay="bg-[linear-gradient(180deg,rgba(10,15,26,0.7)_0%,rgba(10,15,26,0.62)_55%,rgba(10,15,26,0.55)_100%)] lg:bg-[linear-gradient(90deg,rgba(10,15,26,0.72)_0%,rgba(10,15,26,0.6)_40%,rgba(10,15,26,0.35)_72%,rgba(10,15,26,0.4)_100%)]"
          />
          {/* Cool ambient light pooled behind the case panel. */}
          <div aria-hidden className="pointer-events-none absolute inset-0 -z-10 bg-[radial-gradient(44rem_28rem_at_72%_46%,rgba(56,189,248,0.10),transparent_70%)]" />
          {/* Two real columns (each min-width 0, so text wraps inside its own column). The
              text column is stacked ABOVE the panel layer, so the panel's glow and drop
              shadow can never paint over the ends of paragraph lines. */}
          <div className="mx-auto grid max-w-7xl grid-cols-1 items-center gap-20 px-4 pb-24 pt-14 md:px-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)] lg:gap-16 lg:pt-20 xl:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)]">
            <div className="relative z-10 min-w-0" data-testid="hero-copy">
              <TrustBadge />
              <h1 className="mt-6 text-4xl font-semibold leading-[1.08] tracking-tight text-slate-50 md:text-5xl xl:text-6xl">
                Evidence doesn&apos;t exist in isolation.{" "}
                <span className="bg-gradient-to-r from-sky-300 via-cyan-200 to-teal-200 bg-clip-text text-transparent">
                  Neither should your investigation.
                </span>
              </h1>
              <p className="mt-6 max-w-xl text-lg leading-relaxed text-slate-300">
                EvidenceX brings documents, photos, call recordings, video, e-mail and spreadsheets into one workspace.
                Every claim links to the exact page, region, timestamp or cell it came from, and possible
                inconsistencies are surfaced for people to review.
              </p>
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <PrimaryCta />
                <a
                  href="#how-it-works"
                  className="inline-flex items-center gap-2 rounded-lg border border-white/20 bg-navy-950/40 px-5 py-3 text-sm font-medium text-slate-100 backdrop-blur-sm transition hover:border-white/40 hover:bg-white/5"
                >
                  Explore How It Works
                </a>
              </div>
              <ul className="mt-8 flex flex-wrap gap-x-5 gap-y-2 text-sm text-slate-300">
                <li className="flex items-center gap-1.5"><Check className="h-4 w-4 text-processed" aria-hidden /> Runs on your own server</li>
                <li className="flex items-center gap-1.5"><Check className="h-4 w-4 text-processed" aria-hidden /> AI off unless the case owner allows it</li>
                <li className="flex items-center gap-1.5"><Check className="h-4 w-4 text-processed" aria-hidden /> Source-anchored, never summarised away</li>
              </ul>
            </div>
            <HeroVisual />
          </div>
        </section>

        {/* B. The problem — evidence scattered across a desk */}
        <section className="evx-reveal relative isolate" data-section="problem">
          <SectionPhoto
            name="forensic"
            position="50% 50%"
            fallback="scatter"
            overlay="bg-[linear-gradient(90deg,rgba(10,15,26,0.9)_0%,rgba(10,15,26,0.7)_50%,rgba(10,15,26,0.5)_100%)]"
          />
          <div className="mx-auto grid max-w-7xl grid-cols-1 items-center gap-10 px-4 py-24 md:px-8 lg:grid-cols-2">
            <div>
              <p className={EYEBROW}>The problem</p>
              <h2 className={`mt-3 ${H2}`}>
                The answer is usually spread across six file types and three people&apos;s memories.
              </h2>
              <p className={`mt-5 max-w-xl ${LEAD}`}>
                A receipt says 10:30. A witness says “around midday”. A camera frame shows the plate. The ledger counts
                twelve pallets. Each source is easy to read alone; connecting them by hand is slow, and easy to get
                wrong without a record of where each fact came from.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              {FORMATS.map(({ icon: Icon, name }) => (
                <div key={name} className={`${CARD} flex flex-col items-center justify-center gap-2 p-5 text-center`}>
                  <Icon className="h-6 w-6 text-sky-300" aria-hidden />
                  <span className="text-sm font-medium text-slate-200">{name}</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* C. How it works — the evidence wall */}
        <section id="how-it-works" className="evx-reveal relative isolate scroll-mt-20" data-section="how-it-works">
          <SectionPhoto name="wall" position="50% 35%" overlay="bg-navy-950/[0.88]" />
          <div className="mx-auto max-w-7xl px-4 py-24 md:px-8">
            <SectionTitle eyebrow="How it works" title="From raw files to a reviewed, cited report">
              Five steps, each one visible in the workspace. Select a step to see what happens.
            </SectionTitle>
            <PipelineStepper />
          </div>
        </section>

        {/* D. Formats and anchors */}
        <section className="evx-reveal mx-auto max-w-7xl px-4 py-24 md:px-8" data-section="formats">
          <SectionTitle eyebrow="Every format, one standard" title="Each piece of text keeps its physical location">
            Whatever the file, an extracted passage carries a locator you can open.
          </SectionTitle>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {FORMATS.map(({ icon: Icon, name, anchor, note }) => (
              <div key={name} className={`${CARD} p-5 hover:border-sky-500/30`}>
                <div className="flex items-center gap-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg border border-sky-500/30 bg-sky-500/10 text-sky-300">
                    <Icon className="h-5 w-5" aria-hidden />
                  </span>
                  <p className="font-medium text-slate-50">{name}</p>
                </div>
                <p className="mt-3 font-mono text-xs text-sky-200">→ {anchor}</p>
                <p className="mt-1 text-sm text-slate-300">{note}</p>
              </div>
            ))}
          </div>
        </section>

        {/* E. Provenance */}
        <section id="provenance" className="evx-reveal scroll-mt-20 border-y border-white/5 bg-navy-900/50" data-section="provenance">
          <div className="mx-auto max-w-7xl px-4 py-24 md:px-8">
            <SectionTitle eyebrow="Provenance first" title="Click a claim. See exactly where it came from.">
              A claim is a statement with a time, date, quantity, identifier or place. It always quotes its source, and
              stays unverified until a reviewer checks it.
            </SectionTitle>
            <ProvenanceDemo />
          </div>
        </section>

        {/* F. Events and inconsistencies */}
        <section id="events" className="evx-reveal mx-auto max-w-7xl scroll-mt-20 px-4 py-24 md:px-8" data-section="events">
          <div className="grid grid-cols-1 items-start gap-10 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)]">
            <div>
              <p className={EYEBROW}>Events &amp; time</p>
              <h2 className={`mt-3 ${H2}`}>Accounts are compared only when they describe the same thing.</h2>
              <p className={`mt-5 ${LEAD}`}>
                EvidenceX proposes events from shared identifiers, plates, places or, more weakly, the same object word.
                When the link is weak, a reviewer confirms the grouping before any accounts are compared. Small gaps,
                rounding, unstated time zones and missing times are named for what they are, not flagged as
                conflicts.
              </p>
              <ul className="mt-6 space-y-2.5 text-base text-slate-200">
                {[
                  "Planned and actual times are never mixed",
                  "Different stated days are never compared",
                  "Two speakers in one document count as two accounts",
                ].map((t) => (
                  <li key={t} className="flex items-start gap-2.5">
                    <Check className="mt-1 h-4 w-4 shrink-0 text-processed" aria-hidden /> {t}
                  </li>
                ))}
              </ul>
              <div className="mt-8 hidden lg:block">
                <FramedPhoto
                  name="notebook"
                  alt="Illustrative photograph: an open notebook with a hand-drawn map and red string linking pinned photographs, beside a pen and a torch"
                  aspect="aspect-[16/9]"
                  position="50% 55%"
                  fallback="map"
                  caption="Illustration, not case evidence"
                />
              </div>
            </div>
            <EventDemo />
          </div>
        </section>

        {/* G. Graph — the corkboard of red threads */}
        <section id="graph" className="evx-reveal relative isolate scroll-mt-20" data-section="graph">
          <SectionPhoto name="corkboard" position="50% 40%" fallback="threads" overlay="bg-navy-950/[0.7]" />
          <div className="mx-auto max-w-7xl px-4 py-24 md:px-8">
            <SectionTitle eyebrow="Connections" title="See how every file, entity and event relates">
              The knowledge graph is drawn from stored records only. Select a node to light up what it touches, then
              export it as JSON, GraphML or a PDF page.
            </SectionTitle>
            <GraphDemo />
          </div>
        </section>

        {/* H. Review, audit, collaboration, reports */}
        <section className="evx-reveal mx-auto max-w-7xl px-4 py-24 md:px-8" data-section="team">
          <SectionTitle eyebrow="Human in the loop" title="Built for teams that must show their work">
            The system assists. People confirm, reject or defer every finding, and each decision is recorded.
          </SectionTitle>
          <div className="grid grid-cols-1 items-stretch gap-4 lg:grid-cols-[minmax(0,0.8fr)_minmax(0,1.6fr)]">
            <div className="hidden lg:block">
              <FramedPhoto
                name="fingerprints"
                alt="Illustrative photograph: fingerprint cards and photographs spread across a desk beside a red typewriter"
                aspect="aspect-[4/5]"
                position="50% 40%"
                fallback="ridges"
                caption="Illustration, not case evidence"
              />
            </div>
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              {[
                { icon: Users, title: "Roles per case", text: "Owner, editor, reviewer, viewer. Checked by the server on every request; non-members cannot tell a case exists." },
                { icon: Fingerprint, title: "Tamper-evident audit", text: "Each decision is signed by the account that made it and chained by SHA-256. Changing any past record is detected." },
                { icon: Layers, title: "Versioned reports", text: "Investigation and graph reports as PDFs, each with a version number and a content hash." },
                { icon: Bot, title: "AI only with consent", text: "Rule-based by default. AI runs only if a key is configured and the case owner allows it; its output is schema-validated and labelled." },
              ].map(({ icon: Icon, title, text }) => (
                <div key={title} className={`${CARD} p-6`}>
                  <span className="flex h-10 w-10 items-center justify-center rounded-lg border border-sky-500/30 bg-sky-500/10 text-sky-300">
                    <Icon className="h-5 w-5" aria-hidden />
                  </span>
                  <p className="mt-4 font-medium text-slate-50">{title}</p>
                  <p className="mt-1.5 text-sm leading-relaxed text-slate-300">{text}</p>
                </div>
              ))}
            </div>
          </div>
        </section>

        {/* I. Trust and limits */}
        <section id="trust" className="evx-reveal scroll-mt-20 border-y border-white/5 bg-navy-900/50" data-section="trust">
          <div className="mx-auto max-w-7xl px-4 py-24 md:px-8">
            <SectionTitle eyebrow="Honest by design" title="What EvidenceX does, and what it never claims">
              It is an analytical aid. Confidence values are heuristic scores that explain how a rule matched; they
              are not calibrated probabilities that something is true.
            </SectionTitle>
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div className="rounded-2xl border border-processed/30 bg-processed/[0.06] p-6">
                <p className="flex items-center gap-2 text-lg font-semibold text-processed">
                  <ShieldCheck className="h-5 w-5" aria-hidden /> It does
                </p>
                <ul className="mt-4 space-y-3 text-[15px] leading-relaxed text-slate-200">
                  {DOES.map((d) => (
                    <li key={d} className="flex items-start gap-2.5">
                      <Check className="mt-1 h-4 w-4 shrink-0 text-processed" aria-hidden /> {d}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-2xl border border-white/15 bg-navy-950/60 p-6">
                <p className="flex items-center gap-2 text-lg font-semibold text-slate-100">
                  <Scale className="h-5 w-5 text-slate-300" aria-hidden /> It does not
                </p>
                <ul className="mt-4 space-y-3 text-[15px] leading-relaxed text-slate-200">
                  {DOES_NOT.map((d) => (
                    <li key={d} className="flex items-start gap-2.5">
                      <Ban className="mt-1 h-4 w-4 shrink-0 text-slate-400" aria-hidden /> {d}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
            <div className="mt-6 grid grid-cols-1 gap-3 text-sm leading-relaxed text-slate-300 md:grid-cols-3">
              <p className="flex items-start gap-2.5 rounded-xl border border-white/[0.06] bg-navy-950/40 p-4"><Lock className="mt-0.5 h-4 w-4 shrink-0 text-sky-300" aria-hidden /> Uploads are validated by content, stored by hash and never executed.</p>
              <p className="flex items-start gap-2.5 rounded-xl border border-white/[0.06] bg-navy-950/40 p-4"><KeyRound className="mt-0.5 h-4 w-4 shrink-0 text-sky-300" aria-hidden /> Sessions are HttpOnly cookies; only a hash of each token is stored.</p>
              <p className="flex items-start gap-2.5 rounded-xl border border-white/[0.06] bg-navy-950/40 p-4"><Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-sky-300" aria-hidden /> Text in evidence is treated as data, never as instructions to the AI.</p>
            </div>
          </div>
        </section>

        {/* J. Final call to action — the lamp-lit board, on the right half only */}
        <section className="relative isolate overflow-hidden" data-section="cta">
          <SectionPhoto
            name="lampboard"
            position="50% 30%"
            fallback="lamp"
            className="md:left-auto md:w-[58%]"
            overlay="bg-[linear-gradient(90deg,#0a0f1a_0%,rgba(10,15,26,0.7)_35%,rgba(10,15,26,0.4)_100%)]"
          />
          <div className="mx-auto max-w-7xl px-4 py-28 md:px-8">
            <div className="max-w-xl">
              <p className={EYEBROW}>Start a case</p>
              <h2 className={`mt-3 ${H2}`}>Put every source in one place, and keep every link.</h2>
              <p className={`mt-5 ${LEAD}`}>
                Create an account on this server, start a case and upload your first files. Nothing leaves the server
                unless you allow AI for that case.
              </p>
              <div className="mt-8 flex flex-wrap gap-3">
                <PrimaryCta />
                <a href="#how-it-works" className="inline-flex items-center rounded-lg border border-white/20 bg-navy-950/40 px-5 py-3 text-sm font-medium text-slate-100 backdrop-blur-sm transition hover:border-white/40 hover:bg-white/5">
                  Explore How It Works
                </a>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-white/10 bg-navy-950">
        <div className="mx-auto flex max-w-7xl flex-col gap-5 px-4 py-10 text-sm text-slate-400 md:flex-row md:items-start md:justify-between md:px-8">
          <Brand />
          <div className="max-w-xl space-y-2 leading-relaxed">
            <p>
              Built for hackathons, developed with the Kiro AI IDE. Examples on this page use fictional
              data. EvidenceX is an analytical aid and does not determine guilt, detect deception or authenticate evidence.
            </p>
            <p className="text-xs">Photographs on this page are illustrative and are not case evidence.</p>
            <p className="text-xs">
              EvidenceX is free software, licensed under the {LICENSE_NAME}. Third-party components keep their own
              licences.
            </p>
          </div>
          <nav className="flex flex-wrap gap-x-5 gap-y-2" aria-label="Footer">
            <Link href="/login" className="text-slate-300 hover:text-slate-50">Sign in</Link>
            <Link href="/register" className="text-slate-300 hover:text-slate-50">Create account</Link>
            <a href={SOURCE_CODE_URL} rel="noopener noreferrer" className="text-slate-300 hover:text-slate-50">
              Source Code
            </a>
            <a href={LICENSE_URL} rel="noopener noreferrer license" className="text-slate-300 hover:text-slate-50">
              License
            </a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
