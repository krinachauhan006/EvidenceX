"use client";

import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { Paperclip } from "lucide-react";
import { formatBytes } from "@/lib/format";
import type { Segment } from "@/lib/types/processing";
import { Badge } from "@/components/ui/primitives";
import type { ViewerProps } from "@/components/workspace/types";

function data(s: Segment): Record<string, unknown> {
  return (s.data ?? {}) as Record<string, unknown>;
}

export function EmailViewer(props: ViewerProps) {
  const { segments, focusSegmentId, onFocusSegment } = props;
  const headers = segments.filter((s) => s.segment_type === "email_header");
  const textBodies = segments.filter((s) => s.segment_type === "email_body_text");
  const htmlBodies = segments.filter((s) => s.segment_type === "email_body_html");
  const attachments = segments.filter((s) => s.segment_type === "email_attachment");
  const focus = segments.find((s) => s.id === focusSegmentId);
  const [body, setBody] = useState<"text" | "html">(
    focus?.segment_type === "email_body_html" || textBodies.length === 0 ? "html" : "text",
  );
  const rootRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (focus?.segment_type === "email_body_html") setBody("html");
    if (focus?.segment_type === "email_body_text") setBody("text");
    if (focusSegmentId) {
      rootRef.current?.querySelector(`[data-seg="${focusSegmentId}"]`)?.scrollIntoView({ block: "nearest" });
    }
  }, [focus, focusSegmentId]);

  const bodies = body === "text" ? textBodies : htmlBodies;
  const ring = (id: string) => (id === focusSegmentId ? "ring-2 ring-sky-500 bg-sky-500/10" : "");

  return (
    <div ref={rootRef} className="space-y-4">
      <section className="rounded-lg border border-navy-800 bg-navy-900/70 p-3">
        <p className="text-xs font-medium text-slate-300">Headers</p>
        <dl className="mt-2 space-y-1 text-sm">
          {headers.map((h) => {
            const name = h.locator.kind === "email" ? h.locator.name : null;
            return (
              <div
                key={h.id}
                data-seg={h.id}
                onClick={() => onFocusSegment(h.id)}
                className={clsx("grid cursor-pointer grid-cols-[7rem_minmax(0,1fr)] gap-2 rounded px-1.5 py-0.5 hover:bg-navy-800/60", ring(h.id))}
              >
                <dt className="text-slate-500">{name ?? "Header"}</dt>
                <dd className="break-words text-slate-200">
                  {h.text}
                  {name?.toLowerCase() === "date" && typeof data(h).date_iso !== "string" && (
                    <span className="ml-2 text-xs text-slate-500">(could not be parsed; kept as written)</span>
                  )}
                </dd>
              </div>
            );
          })}
          {headers.length === 0 && <p className="text-xs text-slate-500">No headers extracted.</p>}
        </dl>
      </section>

      <section className="rounded-lg border border-navy-800 bg-navy-900/70 p-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-medium text-slate-300">Message body</p>
          <div role="tablist" aria-label="Body version" className="flex gap-1">
            {(["text", "html"] as const).map((k) => (
              <button
                key={k}
                type="button"
                role="tab"
                aria-selected={body === k}
                onClick={() => setBody(k)}
                className={clsx(
                  "rounded-md px-2.5 py-1 text-xs",
                  body === k ? "bg-navy-700 text-slate-100" : "text-slate-400 hover:text-slate-200",
                )}
              >
                {k === "text" ? `Plain text (${textBodies.length})` : `HTML as text (${htmlBodies.length})`}
              </button>
            ))}
          </div>
        </div>
        {body === "html" && (
          <p className="mt-1 text-[11px] text-slate-500">
            HTML bodies are never rendered. This is the text extracted from the HTML; scripts, images
            and remote content are not loaded.
          </p>
        )}
        {bodies.length === 0 && <p className="mt-2 text-xs text-slate-500">No {body === "text" ? "plain-text" : "HTML"} body in this message.</p>}
        {bodies.map((b) => (
          <pre
            key={b.id}
            data-seg={b.id}
            onClick={() => onFocusSegment(b.id)}
            className={clsx(
              "mt-2 max-h-[28rem] cursor-pointer overflow-auto whitespace-pre-wrap break-words rounded bg-navy-950 p-3 font-sans text-sm text-slate-200",
              ring(b.id),
            )}
          >
            {b.text}
          </pre>
        ))}
      </section>

      <section className="rounded-lg border border-navy-800 bg-navy-900/70 p-3">
        <p className="text-xs font-medium text-slate-300">Attachments ({attachments.length})</p>
        <p className="text-[11px] text-slate-500">
          Metadata only. Attachment content is not opened, extracted or analysed.
        </p>
        <ul className="mt-2 space-y-1">
          {attachments.map((a) => {
            const d = data(a);
            return (
              <li key={a.id} data-seg={a.id} className={clsx("flex flex-wrap items-center gap-2 rounded px-1.5 py-1 text-sm", ring(a.id))}>
                <Paperclip className="h-3.5 w-3.5 text-slate-500" aria-hidden />
                <span className="text-slate-200">{typeof d.filename === "string" ? d.filename : "(unnamed)"}</span>
                {typeof d.content_type === "string" && <span className="text-xs text-slate-500">{d.content_type}</span>}
                {typeof d.size === "number" && <span className="text-xs text-slate-500">{formatBytes(d.size)}</span>}
                <Badge>metadata only</Badge>
              </li>
            );
          })}
        </ul>
      </section>
    </div>
  );
}
