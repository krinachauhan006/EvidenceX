// Pure, defensive readers for the free-form `data` object on a segment.
// `data` comes from the extractor and is untrusted, so every field is checked.
// Anything that does not match returns null and the caller falls back to `text`.

export interface SegmentCell {
  column: string;
  /** Exact value as extracted, converted to text for display only. */
  value: string;
  /** Spreadsheet coordinate such as "C5", when the extractor provided one. */
  coord: string | null;
  typeHint: string | null;
  truncated: boolean;
  /** Spreadsheet formula text such as "=SUM(B2:B3)". Never calculated by EvidenceX. */
  formula: string | null;
  /** True when a formula cell has no cached result, so its value is unknown. */
  noCachedValue: boolean;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

/** Cells of a table row, or null if `data` does not carry a valid cell list. */
export function parseCells(data: unknown): SegmentCell[] | null {
  if (!isRecord(data) || !Array.isArray(data.cells)) return null;
  const cells: SegmentCell[] = [];
  for (const raw of data.cells) {
    if (!isRecord(raw) || typeof raw.column !== "string") return null;
    const v = raw.value;
    let value: string;
    if (typeof v === "string") value = v;
    else if (typeof v === "number" || typeof v === "boolean") value = String(v);
    else if (v === null || v === undefined) value = "";
    else return null;
    cells.push({
      column: raw.column,
      value,
      coord: typeof raw.coord === "string" ? raw.coord : null,
      typeHint: typeof raw.type_hint === "string" ? raw.type_hint : null,
      truncated: raw.truncated === true,
      formula: typeof raw.formula === "string" ? raw.formula : null,
      noCachedValue: raw.no_cached_value === true,
    });
  }
  return cells;
}

/** Raw header names of a table header row, or null. */
export function parseHeaders(data: unknown): string[] | null {
  if (!isRecord(data) || !Array.isArray(data.headers_raw)) return null;
  if (!data.headers_raw.every((h) => typeof h === "string")) return null;
  return data.headers_raw as string[];
}

/** A short list of well-known metadata values worth showing without opening JSON. */
export function metadataHighlights(
  metadata: Record<string, unknown> | null | undefined,
): { label: string; value: string }[] {
  if (!isRecord(metadata)) return [];
  const known: [string, string][] = [
    ["encoding", "Encoding"],
    ["delimiter", "Delimiter"],
    ["column_count", "Columns"],
    ["data_row_count", "Data rows"],
    ["blank_rows", "Blank rows"],
    ["sheet_count", "Sheets"],
    ["date_system", "Date system"],
    ["page_count", "Pages"],
    ["pages_extracted", "Pages read"],
    ["attachment_count", "Attachments"],
    ["body_text_parts", "Text bodies"],
    ["body_html_parts", "HTML bodies"],
    ["width", "Width (px)"],
    ["height", "Height (px)"],
    ["ocr_language", "OCR language"],
    ["line_count", "OCR lines"],
    ["word_count", "OCR words"],
    ["duration_seconds", "Duration (s)"],
    ["language", "Language"],
    ["model", "Speech model"],
  ];
  const out: { label: string; value: string }[] = [];
  for (const [key, label] of known) {
    const v = metadata[key];
    if (typeof v === "number" && Number.isFinite(v)) out.push({ label, value: String(v) });
    else if (typeof v === "string" && v !== "") {
      out.push({ label, value: v === "\t" ? "tab" : v });
    }
  }
  return out;
}
