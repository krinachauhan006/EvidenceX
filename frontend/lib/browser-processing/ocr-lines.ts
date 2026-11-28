// Tesseract.js output -> OCR lines in the server's shape. Pure (unit-tested).
//
// Mirrors backend group_words_into_lines (app/modules/processing/extractors/
// ocr_engine.py): word text is trimmed, empty words and words with a negative
// confidence are dropped, confidence is engine-reported 0..100 scaled to 0..1, the
// line text is the words joined by single spaces, the line box is the union of the
// word boxes clamped to the image, and the line confidence is the mean word confidence.
// The server re-checks all of it; this only avoids sending what it would refuse.

export type Box = [number, number, number, number];

export interface OcrWord {
  text: string;
  bbox: Box;
  confidence: number;
}

export interface OcrLine {
  text: string;
  bbox: Box;
  confidence: number | null;
  words: OcrWord[];
}

/** The subset of Tesseract.js `recognize(..., { blocks: true })` output that is used. */
export interface TesseractBox {
  x0: number;
  y0: number;
  x1: number;
  y1: number;
}
export interface TesseractWord {
  text: string;
  confidence: number;
  bbox: TesseractBox;
}
export interface TesseractLine {
  words: TesseractWord[];
}
export interface TesseractParagraph {
  lines: TesseractLine[];
}
export interface TesseractBlock {
  paragraphs: TesseractParagraph[];
}

const round2 = (v: number) => Math.round(v * 100) / 100;
const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

/**
 * `scale`: how much larger the canvas the engine read was than the original image
 * (boxes are divided by it, so they refer to the original pixels).
 */
export function linesFromBlocks(
  blocks: readonly TesseractBlock[] | null | undefined,
  width: number,
  height: number,
  scale = 1,
): OcrLine[] {
  const out: OcrLine[] = [];
  for (const block of blocks ?? []) {
    for (const paragraph of block.paragraphs ?? []) {
      for (const line of paragraph.lines ?? []) {
        const words: OcrWord[] = [];
        for (const w of line.words ?? []) {
          // The server accepts words up to 200 and lines up to 4,000 characters.
          const text = (w.text ?? "").trim().slice(0, 200);
          if (!text || !(w.confidence >= 0)) continue;
          const b = w.bbox;
          if (![b.x0, b.y0, b.x1, b.y1].every(Number.isFinite)) continue;
          words.push({
            text,
            bbox: [
              round2(clamp(b.x0 / scale, 0, width)),
              round2(clamp(b.y0 / scale, 0, height)),
              round2(clamp(b.x1 / scale, 0, width)),
              round2(clamp(b.y1 / scale, 0, height)),
            ],
            confidence: Math.round(clamp(w.confidence / 100, 0, 1) * 10000) / 10000,
          });
        }
        if (words.length === 0) continue;
        const bbox: Box = [
          Math.min(...words.map((w) => w.bbox[0])),
          Math.min(...words.map((w) => w.bbox[1])),
          Math.max(...words.map((w) => w.bbox[2])),
          Math.max(...words.map((w) => w.bbox[3])),
        ];
        const confidence = words.reduce((s, w) => s + w.confidence, 0) / words.length;
        out.push({
          text: words.map((w) => w.text).join(" ").slice(0, 4000),
          bbox,
          confidence: Math.round(confidence * 10000) / 10000,
          words,
        });
      }
    }
  }
  return out;
}
