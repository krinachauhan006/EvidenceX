"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import clsx from "clsx";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { Segment } from "@/lib/types/processing";
import { parseCells, parseHeaders } from "@/components/evidence/segment-data";
import { BUTTON, INPUT } from "@/components/ui/primitives";
import { claimsBySegment, type ViewerProps } from "@/components/workspace/types";
import { rowDetail } from "@/components/workspace/table-detail";

const PAGE = 50;

interface Sheet {
  name: string;
  columns: string[];
  headers: string[] | null;
  headerRow: number | null;
  rows: Segment[];
}

function sheetOf(s: Segment): string {
  return s.locator.kind === "xlsx" ? s.locator.sheet : "CSV";
}

function rowOf(s: Segment): number | null {
  return s.locator.kind === "xlsx" || s.locator.kind === "csv" ? s.locator.row : null;
}

function buildSheets(segments: Segment[]): Sheet[] {
  const map = new Map<string, Sheet>();
  for (const s of segments) {
    if (s.segment_type !== "table_header" && s.segment_type !== "table_row") continue;
    const name = sheetOf(s);
    const sheet = map.get(name) ?? { name, columns: [], headers: null, headerRow: null, rows: [] };
    map.set(name, sheet);
    if (s.segment_type === "table_header") {
      const data = s.data as { header_keys?: unknown } | null;
      const keys = Array.isArray(data?.header_keys) ? data!.header_keys.filter((k): k is string => typeof k === "string") : null;
      sheet.headers = parseHeaders(s.data);
      sheet.headerRow = rowOf(s);
      if (keys) sheet.columns = keys;
    } else {
      sheet.rows.push(s);
      for (const c of parseCells(s.data) ?? []) {
        if (!sheet.columns.includes(c.column)) sheet.columns.push(c.column);
      }
    }
  }
  return [...map.values()];
}

export function TableViewer(props: ViewerProps) {
  const { segments, claims, focusSegmentId, onFocusSegment } = props;
  const sheets = useMemo(() => buildSheets(segments), [segments]);
  const anchored = useMemo(() => claimsBySegment(claims), [claims]);
  const focusSeg = segments.find((s) => s.id === focusSegmentId) ?? null;
  const [sheetName, setSheetName] = useState<string>(focusSeg ? sheetOf(focusSeg) : sheets[0]?.name ?? "");
  const [offset, setOffset] = useState(0);
  const tableRef = useRef<HTMLDivElement | null>(null);
  const sheet = sheets.find((s) => s.name === sheetName) ?? sheets[0];

  useEffect(() => {
    if (!focusSeg || !sheet) return;
    const name = sheetOf(focusSeg);
    if (name !== sheetName) setSheetName(name);
    const target = sheets.find((s) => s.name === name);
    const index = target?.rows.findIndex((r) => r.id === focusSeg.id) ?? -1;
    if (index >= 0) setOffset(Math.floor(index / PAGE) * PAGE);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusSeg]);

  useEffect(() => {
    if (!focusSegmentId || !tableRef.current) return;
    tableRef.current.querySelector(`[data-seg="${focusSegmentId}"]`)?.scrollIntoView({ block: "center" });
  }, [focusSegmentId, offset, sheetName]);

  if (!sheet) return <p className="text-sm text-slate-500">No table rows were extracted.</p>;
  const page = sheet.rows.slice(offset, offset + PAGE);
  const hasFormula = sheet.rows.some((r) => (parseCells(r.data) ?? []).some((c) => c.formula));

  return (
    <div>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2 text-xs text-slate-400">
        <div className="flex items-center gap-2">
          {sheets.length > 1 && (
            <select
              value={sheet.name}
              onChange={(e) => {
                setSheetName(e.target.value);
                setOffset(0);
              }}
              className={`${INPUT} w-auto py-1 text-xs`}
              aria-label="Worksheet"
            >
              {sheets.map((s) => (
                <option key={s.name} value={s.name}>
                  Sheet: {s.name} ({s.rows.length} rows)
                </option>
              ))}
            </select>
          )}
          <span>
            {sheet.rows.length} data row{sheet.rows.length === 1 ? "" : "s"}
            {sheet.headerRow ? ` · header in row ${sheet.headerRow}` : ""}
          </span>
        </div>
        {hasFormula && (
          <span>
            <span className="rounded bg-navy-700 px-1 font-mono">ƒ</span> = formula cell: the value shown is the
            cached result saved in the file; EvidenceX never calculates formulas.
          </span>
        )}
      </div>
      <p className="mb-1.5 text-[11px] text-slate-500">
        Long values are shortened in the grid (marked …). Select a row number to see every cell of
        that row in full.
      </p>
      <div ref={tableRef} className="max-h-[40rem] overflow-auto rounded-lg border border-navy-800">
        <table className="min-w-full border-collapse text-xs">
          <thead className="sticky top-0 z-20 bg-navy-850">
            <tr>
              <th className="sticky left-0 z-30 border-b border-r border-navy-700 bg-navy-850 px-2 py-1.5 text-left align-top font-medium text-slate-400">
                Row
              </th>
              {sheet.columns.map((c, i) => (
                <th
                  key={c}
                  className="whitespace-nowrap border-b border-navy-700 px-2 py-1.5 text-left align-top font-medium text-slate-300"
                  title={`Key: ${c}`}
                >
                  {sheet.headers?.[i] ?? c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {page.map((r) => {
              const cells = new Map((parseCells(r.data) ?? []).map((c) => [c.column, c]));
              const claimCount = anchored.get(r.id)?.length ?? 0;
              const selected = r.id === focusSegmentId;
              return (
                <tr
                  key={r.id}
                  data-seg={r.id}
                  onClick={() => onFocusSegment(r.id)}
                  className={clsx(
                    "cursor-pointer border-b border-navy-800/70",
                    selected ? "bg-sky-500/15" : "hover:bg-navy-800/50",
                  )}
                >
                  {/* Same top alignment as the values; sticky so it stays visible when
                      scrolling sideways through wide sheets. */}
                  <td
                    className={clsx(
                      "sticky left-0 z-10 border-r border-navy-800 px-1 py-0.5 align-top",
                      selected ? "bg-[#13253a]" : "bg-navy-900",
                    )}
                  >
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onFocusSegment(r.id);
                      }}
                      aria-pressed={selected}
                      aria-label={`Row ${rowOf(r) ?? "?"}: show every cell in full`}
                      className="whitespace-nowrap rounded px-1 py-0.5 font-mono leading-5 text-slate-400 hover:bg-navy-700 hover:text-slate-100"
                    >
                      {rowOf(r) ?? "?"}
                      {claimCount > 0 && (
                        <span className="ml-1 text-sky-300" title={`${claimCount} claim(s)`}>
                          •
                        </span>
                      )}
                    </button>
                  </td>
                  {sheet.columns.map((col) => {
                    const c = cells.get(col);
                    const full = c ? (c.noCachedValue ? `no cached value (${c.formula})` : c.value) : "";
                    return (
                      <td
                        key={col}
                        className="max-w-[16rem] whitespace-nowrap px-2 py-1 align-top leading-5 text-slate-200"
                        title={c ? `${c.coord ? `Cell ${c.coord}: ` : ""}${full}` : undefined}
                      >
                        {c ? (
                          <span className="flex min-w-0 items-baseline gap-1">
                            {c.formula && (
                              <span className="shrink-0 rounded bg-navy-700 px-1 font-mono text-[10px] text-slate-300" title={`Formula ${c.formula}`}>
                                ƒ
                              </span>
                            )}
                            <span className={clsx("min-w-0 truncate", c.noCachedValue && "italic text-slate-500")}>
                              {full}
                            </span>
                            {c.truncated && <span className="shrink-0 text-slate-500">(truncated)</span>}
                          </span>
                        ) : null}
                      </td>
                    );
                  })}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <RowDetailPanel
        segment={sheet.rows.find((r) => r.id === focusSegmentId) ?? null}
        columns={sheet.columns}
        headers={sheet.headers}
        onClose={() => onFocusSegment(null)}
      />
      {sheet.rows.length > PAGE && (
        <div className="mt-2 flex items-center justify-between text-xs text-slate-400">
          <button type="button" className={BUTTON} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            <ChevronLeft className="h-3.5 w-3.5" aria-hidden /> Previous
          </button>
          <span>
            Rows {offset + 1}–{Math.min(offset + PAGE, sheet.rows.length)} of {sheet.rows.length}
          </span>
          <button type="button" className={BUTTON} disabled={offset + PAGE >= sheet.rows.length} onClick={() => setOffset(offset + PAGE)}>
            Next <ChevronRight className="h-3.5 w-3.5" aria-hidden />
          </button>
        </div>
      )}
    </div>
  );
}

/** Every cell of the selected row, unshortened, with its spreadsheet coordinate. */
function RowDetailPanel({
  segment,
  columns,
  headers,
  onClose,
}: {
  segment: Segment | null;
  columns: string[];
  headers: string[] | null;
  onClose: () => void;
}) {
  if (!segment) return null;
  const entries = rowDetail(parseCells(segment.data) ?? [], columns, headers);
  return (
    <section
      aria-label={`All cells of row ${rowOf(segment) ?? "?"}`}
      className="mt-3 rounded-lg border border-navy-700 bg-navy-900/80 p-3"
    >
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-slate-200">
          Row {rowOf(segment) ?? "?"} · all {entries.length} cells, complete values as extracted
        </p>
        <button type="button" onClick={onClose} className={BUTTON}>
          Close
        </button>
      </div>
      <dl className="mt-2 grid gap-x-6 gap-y-1.5 text-xs sm:grid-cols-2 xl:grid-cols-3">
        {entries.map((e) => (
          <div key={e.key} className="min-w-0">
            <dt className="text-slate-500">
              {e.label}
              {e.coord && <span className="ml-1 font-mono text-slate-600">{e.coord}</span>}
              {e.formula && <span className="ml-1 font-mono text-slate-600">ƒ {e.formula}</span>}
            </dt>
            <dd className="whitespace-pre-wrap break-words text-slate-100">
              {!e.present ? (
                <span className="text-slate-600">(no cell)</span>
              ) : e.noCachedValue ? (
                <span className="italic text-slate-500">no cached value; formulas are never calculated</span>
              ) : e.value === "" ? (
                <span className="text-slate-600">(empty)</span>
              ) : (
                e.value
              )}
              {e.truncatedAtExtraction && (
                <span className="ml-1 text-slate-500">(cut by the extractor&apos;s cell size limit)</span>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
