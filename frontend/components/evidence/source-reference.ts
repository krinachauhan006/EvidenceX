// Pure helpers that turn a segment's typed locator into a readable source
// reference. No React, no side effects. Nothing is invented: a missing or
// unrecognized locator yields an explicit "unavailable" reference.

import type { BBox, Locator } from "@/lib/types/processing";

export interface SourceReference {
  /** Short reference, for example `Page 3` or `Sheet "Payments" · C5`. */
  label: string;
  /** Extra detail such as a bounding box, or null when there is none. */
  detail: string | null;
  /** False when the location is missing or not understood. */
  available: boolean;
}

const UNAVAILABLE: SourceReference = {
  label: "Source location unavailable",
  detail: null,
  available: false,
};

function num(value: number): string {
  if (!Number.isFinite(value)) return "?";
  return String(Math.round(value * 10) / 10);
}

function isBBox(value: unknown): value is BBox {
  return (
    Array.isArray(value) &&
    value.length === 4 &&
    value.every((n) => typeof n === "number" && Number.isFinite(n))
  );
}

function bboxText(bbox: BBox): string {
  return `[${bbox.map(num).join(", ")}]`;
}

/** hh:mm:ss.t, for example 72.3 -> "00:01:12.3". */
export function formatTimestamp(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds < 0) return "?";
  const tenths = Math.round(seconds * 10);
  const t = tenths % 10;
  const totalSeconds = Math.floor(tenths / 10);
  const s = totalSeconds % 60;
  const m = Math.floor(totalSeconds / 60) % 60;
  const h = Math.floor(totalSeconds / 3600);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(h)}:${pad(m)}:${pad(s)}.${t}`;
}

// "C5" or "C5:C5" -> a single cell.
function singleCell(range: string): string | null {
  const m = /^([A-Za-z]{1,3}\d+)(?::([A-Za-z]{1,3}\d+))?$/.exec(range.trim());
  if (!m) return null;
  if (m[2] === undefined || m[2].toUpperCase() === m[1].toUpperCase()) return m[1].toUpperCase();
  return null;
}

/** Describe where a segment came from. Accepts null/undefined and unknown kinds. */
export function describeLocator(locator: Locator | null | undefined): SourceReference {
  if (!locator || typeof locator !== "object") return UNAVAILABLE;

  switch (locator.kind) {
    case "pdf": {
      const parts: string[] = [];
      if (isBBox(locator.bbox)) parts.push(`Box ${bboxText(locator.bbox)} pt`);
      if (
        typeof locator.page_width === "number" &&
        typeof locator.page_height === "number"
      ) {
        parts.push(`page ${num(locator.page_width)} × ${num(locator.page_height)} pt`);
      }
      return {
        label: `Page ${locator.page}`,
        detail: parts.length ? parts.join(" · ") : null,
        available: true,
      };
    }

    case "image": {
      if (!isBBox(locator.bbox)) return UNAVAILABLE;
      const [x0, y0, x1, y1] = locator.bbox;
      return {
        label: `Region (${num(x0)}, ${num(y0)}) – (${num(x1)}, ${num(y1)}) px`,
        detail: `Image ${num(locator.width)} × ${num(locator.height)} px`,
        available: true,
      };
    }

    case "audio":
      return {
        label: `${formatTimestamp(locator.start)} – ${formatTimestamp(locator.end)}`,
        detail: null,
        available: true,
      };

    case "csv": {
      const column = locator.column ? ` · Column "${locator.column}"` : "";
      return {
        label: `Row ${locator.row} · Line ${locator.line}${column}`,
        detail: null,
        available: true,
      };
    }

    case "xlsx": {
      const cell = singleCell(locator.range);
      return {
        label: cell
          ? `Sheet "${locator.sheet}" · ${cell}`
          : `Sheet "${locator.sheet}" · Row ${locator.row} · ${locator.range}`,
        detail: null,
        available: true,
      };
    }

    case "email": {
      const part = locator.index != null ? ` · part ${locator.index + 1}` : "";
      switch (locator.part) {
        case "header":
          return {
            label: locator.name ? `Header: ${locator.name}` : "Header",
            detail: null,
            available: true,
          };
        case "body_text":
          return { label: `Body (text)${part}`, detail: null, available: true };
        case "body_html":
          return { label: `Body (HTML, as text)${part}`, detail: null, available: true };
        case "attachment": {
          const number = locator.index != null ? ` ${locator.index + 1}` : "";
          return {
            label: `Attachment${number}${locator.name ? ` · ${locator.name}` : ""}`,
            detail: null,
            available: true,
          };
        }
        default:
          return UNAVAILABLE;
      }
    }

    case "video": {
      const region = isBBox(locator.bbox) ? `Text region ${bboxText(locator.bbox)} px` : null;
      return {
        label: `Frame at ${formatTimestamp(locator.t)}`,
        detail: [region, `frame ${num(locator.frame_width)} × ${num(locator.frame_height)} px`]
          .filter(Boolean)
          .join(" · "),
        available: true,
      };
    }

    default:
      return UNAVAILABLE;
  }
}

const SEGMENT_TYPE_LABELS: Record<string, string> = {
  table_header: "Header row",
  table_row: "Table row",
  pdf_text_block: "Text block",
  ocr_line: "OCR line",
  transcript_segment: "Transcript segment",
  email_header: "Email header",
  email_body_text: "Body (text)",
  email_body_html: "Body (HTML as text)",
  email_attachment: "Attachment",
  video_frame: "Sampled video frame",
  video_ocr_line: "Text on a video frame",
};

export function segmentTypeLabel(segmentType: string): string {
  const known = SEGMENT_TYPE_LABELS[segmentType];
  if (known) return known;
  const spaced = segmentType.replace(/_/g, " ").trim();
  return spaced ? spaced.charAt(0).toUpperCase() + spaced.slice(1) : "Segment";
}
