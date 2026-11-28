// In-browser processing: the pure rules (capability checks, OCR line mapping,
// transcript mapping, bounded frame sampling, payload encoding, error codes) and
// source-level guarantees (lazy loading, self-hosted engines, claim order).
// The engines themselves (Tesseract.js, Whisper) are NOT run here.
// Run: node --experimental-strip-types --no-warnings --test tests/browser-processing.test.mjs
import assert from "node:assert/strict";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import { test } from "node:test";
import { fileURLToPath } from "node:url";

import { SIMD_PROBE, assessSupport } from "../lib/browser-processing/capabilities.ts";
import { EngineError, MediaDecodeError, failureCode, isOutOfMemory } from "../lib/browser-processing/errors.ts";
import { linesFromBlocks } from "../lib/browser-processing/ocr-lines.ts";
import { MAX_BODY_BYTES, encodeResultBody, sha256Hex } from "../lib/browser-processing/payload.ts";
import { frameSchedule, segmentsFromChunks } from "../lib/browser-processing/transcript.ts";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const src = (p) => readFileSync(join(ROOT, p), "utf8");

const FULL = {
  webAssembly: true,
  wasmSimd: true,
  worker: true,
  canvas2d: true,
  createImageBitmap: true,
  audioContext: true,
  subtleCrypto: true,
  webGpu: true,
  deviceMemoryGb: 8,
  canPlayVideo: "probably",
  canPlayAudio: "probably",
};

// --- capabilities -----------------------------------------------------------------

test("a current desktop browser supports every kind, with no notes when WebGPU exists", () => {
  for (const kind of ["image", "audio", "video"]) {
    assert.deepEqual(assessSupport(kind, FULL), { supported: true, reason: null, notes: [] });
  }
});

test("WebGPU is never required: without it processing runs on WebAssembly, with a note", () => {
  const s = assessSupport("audio", { ...FULL, webGpu: false });
  assert.equal(s.supported, true);
  assert.match(s.notes.join(" "), /WebGPU is not available.*WebAssembly/);
});

test("missing essentials make the browser unsupported, with a reason, before any claim", () => {
  const cases = [
    ["image", { webAssembly: false }, /WebAssembly/],
    ["image", { worker: false }, /Web Workers/],
    ["image", { subtleCrypto: false }, /secure \(https\)/],
    ["image", { createImageBitmap: false }, /cannot draw images/],
    ["audio", { audioContext: false }, /cannot decode audio/],
    ["audio", { wasmSimd: false }, /SIMD/],
    ["audio", { canPlayAudio: "" }, /cannot decode this audio format/],
    ["video", { canPlayVideo: "" }, /cannot decode this video format/],
  ];
  for (const [kind, change, reason] of cases) {
    const s = assessSupport(kind, { ...FULL, ...change });
    assert.equal(s.supported, false, JSON.stringify(change));
    assert.match(s.reason, reason);
  }
});

test("a video can still be read without speech support; the soundtrack is flagged", () => {
  const s = assessSupport("video", { ...FULL, audioContext: false });
  assert.equal(s.supported, true);
  assert.match(s.notes.join(" "), /soundtrack cannot be transcribed/);
  assert.match(assessSupport("audio", { ...FULL, deviceMemoryGb: 2 }).notes.join(" "), /little memory/);
});

test("the SIMD probe is a valid SIMD WebAssembly module", () => {
  assert.equal(WebAssembly.validate(SIMD_PROBE), true);
  const broken = SIMD_PROBE.slice(0, SIMD_PROBE.length - 3);
  assert.equal(WebAssembly.validate(broken), false);
});

// --- OCR lines ------------------------------------------------------------------------

const word = (text, confidence, x0, y0, x1, y1) => ({ text, confidence, bbox: { x0, y0, x1, y1 } });

test("Tesseract.js words are grouped into lines exactly like the server's OCR", () => {
  const blocks = [
    {
      paragraphs: [
        {
          lines: [
            { words: [word(" Truck ", 90, 10, 10, 50, 30), word("", 99, 0, 0, 1, 1), word("arrived", 70, 55, 12, 120, 32)] },
            { words: [word("noise", -1, 0, 0, 5, 5)] }, // negative confidence: dropped
          ],
        },
      ],
    },
  ];
  const [line, ...rest] = linesFromBlocks(blocks, 200, 100);
  assert.equal(rest.length, 0);
  assert.equal(line.text, "Truck arrived");
  assert.deepEqual(line.bbox, [10, 10, 120, 32]);
  assert.equal(line.confidence, 0.8);
  assert.deepEqual(line.words.map((w) => w.confidence), [0.9, 0.7]);
});

test("boxes are mapped back from a scaled canvas and clamped to the image", () => {
  const blocks = [{ paragraphs: [{ lines: [{ words: [word("Edge", 80, 100, 20, 420, 60)] }] }] }];
  const [line] = linesFromBlocks(blocks, 200, 100, 2); // the canvas was twice the size
  assert.deepEqual(line.bbox, [50, 10, 200, 30]); // 420 / 2 = 210 clamped to 200
  assert.deepEqual(linesFromBlocks(null, 10, 10), []);
});

// --- transcript and frames ---------------------------------------------------------

test("Whisper chunks become segments inside the recording, with no invented text", () => {
  const out = segmentsFromChunks(
    [
      { text: " Hello there. ", timestamp: [0, 2.5] },
      { text: "   ", timestamp: [2.5, 3] },
      { text: "Cut off", timestamp: [28.2, null] },
      { text: "late", timestamp: [null, 99] },
    ],
    30,
  );
  assert.deepEqual(out, [
    { start: 0, end: 2.5, text: "Hello there." },
    { start: 28.2, end: 30, text: "Cut off" },
    { start: 30, end: 30, text: "late" },
  ]);
});

test("video sampling is bounded: at most max_frames + 1 frames, widened for long videos", () => {
  assert.deepEqual(frameSchedule(25, 10, 60), { times: [0, 10, 20], interval: 10 });
  const long = frameSchedule(3600, 10, 60);
  assert.equal(long.times.length, 60);
  assert.equal(long.interval, 60);
  assert.ok(long.times.every((t, i) => i === 0 || t > long.times[i - 1]));
  assert.deepEqual(frameSchedule(0, 10, 60).times, [0]);
  assert.ok(frameSchedule(1e6, 0.5, 5).times.length <= 6);
});

// --- payload --------------------------------------------------------------------------

function imageBody(lines) {
  return {
    run_number: 1,
    source_sha256: "a".repeat(64),
    duration_ms: 10,
    engine: { ocr_engine_version: "7.0.0", device: "wasm" },
    result: { kind: "image", width: 100, height: 100, language: "eng", lines },
  };
}

test("an oversized body drops per-word boxes first, then gives up", () => {
  const words = Array.from({ length: 200 }, (_, i) => ({ text: `w${i}`, bbox: [0, 0, 1, 1], confidence: 0.5 }));
  const lines = Array.from({ length: 50 }, () => ({ text: "line", bbox: [0, 0, 10, 10], confidence: 0.5, words }));
  const small = encodeResultBody(imageBody(lines.slice(0, 1)));
  assert.equal(JSON.parse(small).result.lines[0].words.length, 200);
  const slim = JSON.parse(encodeResultBody(imageBody(lines), 50_000));
  assert.ok(slim.result.lines.every((l) => l.words.length === 0 && l.text === "line"));
  assert.equal(encodeResultBody(imageBody(lines), 100), null);
  assert.equal(MAX_BODY_BYTES, 4_000_000); // below Vercel's 4.5 MB request limit
});

test("the SHA-256 check uses the standard digest", async () => {
  const hex = await sha256Hex(new TextEncoder().encode("abc").buffer);
  assert.equal(hex, "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
});

test("errors map to the failure codes the server accepts", () => {
  assert.equal(failureCode(new DOMException("x", "AbortError")), "interrupted");
  assert.equal(failureCode(new RangeError("Array buffer allocation failed")), "browser_out_of_memory");
  assert.equal(failureCode(new Error("RuntimeError: memory access out of bounds")), "browser_out_of_memory");
  assert.equal(failureCode(new MediaDecodeError("no")), "browser_decode_failed");
  assert.equal(failureCode(new EngineError("no")), "browser_engine_failed");
  assert.equal(failureCode("weird"), "browser_engine_failed");
  assert.equal(isOutOfMemory(new Error("fine")), false);
});

// --- source-level guarantees ---------------------------------------------------------

test("nothing is claimed before the browser is checked and the file is verified", () => {
  const run = src("lib/browser-processing/run.ts");
  const body = run.slice(run.indexOf("export async function processInBrowser"));
  const order = [
    "assessSupport(",
    "fetchEvidenceBlob(",
    "sha256Hex(",
    "canDecodeVideoPicture(",
    "mediaDuration(",
    "claimForBrowser(",
  ].map((s) =>
    body.indexOf(s),
  );
  assert.ok(order.every((i) => i > 0), String(order));
  assert.deepEqual([...order].sort((a, b) => a - b), order);
  // Completed comes from the server's response to the submission, never set locally.
  assert.match(body, /return await submitBrowserResult\(/);
  assert.doesNotMatch(src("hooks/use-browser-processing.ts"), /"completed"/);
});

test("the engines are loaded lazily and only from this site", () => {
  // No page or component imports an engine package directly.
  const offenders = [];
  const walk = (dir) => {
    for (const name of readdirSync(join(ROOT, dir))) {
      const rel = join(dir, name);
      if (statSync(join(ROOT, rel)).isDirectory()) walk(rel);
      else if (/\.(tsx?|mjs)$/.test(name) && /from "(tesseract\.js|@huggingface\/transformers)"/.test(src(rel))) {
        offenders.push(rel);
      }
    }
  };
  for (const dir of ["app", "components", "hooks", "lib"]) walk(dir);
  assert.deepEqual(offenders, []);
  assert.match(src("hooks/use-browser-processing.ts"), /await import\("@\/lib\/browser-processing\/run"\)/);
  assert.match(src("lib/browser-processing/ocr-engine.ts"), /await import\("tesseract\.js"\)/);

  const ocr = src("lib/browser-processing/ocr-engine.ts");
  for (const p of ["/engines/tesseract/worker.min.js", "/engines/tesseract/core", "/engines/tesseract/lang"]) {
    assert.ok(ocr.includes(p), p);
  }
  assert.doesNotMatch(ocr, /https?:\/\//);
  const worker = src("lib/browser-processing/speech-worker.mjs");
  assert.match(worker, /from "\.\/transformers\/transformers\.min\.js"/);
  assert.match(worker, /new URL\("\.\/ort\/", self\.location\.href\)/);
  assert.match(src("lib/browser-processing/speech-engine.ts"), /\/engines\/speech-worker\.mjs/);
  assert.match(worker, /allowLocalModels = false/);
  assert.match(worker, /useBrowserCache = true/);
  // The worker receives samples and posts results back; it never sends them anywhere.
  assert.doesNotMatch(worker, /fetch\(|XMLHttpRequest|sendBeacon/);
  // The transcription language is stated (never silently assumed) and recorded on the run.
  assert.match(worker, /language: msg\.language/);
  assert.match(src("lib/browser-processing/speech-engine.ts"), /SPEECH_LANGUAGE = "english"/);
  assert.match(src("lib/browser-processing/run.ts"), /language: SPEECH_LANGUAGE/);
});

test("the engine files are copied before dev and build, and are not committed", () => {
  const pkg = JSON.parse(src("package.json"));
  assert.equal(pkg.scripts.prebuild, "node scripts/copy-browser-engines.mjs");
  assert.equal(pkg.scripts.predev, "node scripts/copy-browser-engines.mjs");
  for (const dep of ["tesseract.js", "@tesseract.js-data/eng", "@huggingface/transformers"]) {
    assert.match(pkg.dependencies[dep], /^\d+\.\d+\.\d+$/, `${dep} is pinned`);
  }
  const copy = src("scripts/copy-browser-engines.mjs");
  for (const f of ["worker.min.js", "eng.traineddata.gz", "transformers.min.js", "speech-worker.mjs", "ort-wasm-simd-threaded.asyncify.wasm"]) {
    assert.ok(copy.includes(f), f);
  }
  assert.match(readFileSync(join(ROOT, "..", ".gitignore"), "utf8"), /^frontend\/public\/engines\/\r?$/m);
  // The engine version constants match the installed packages.
  assert.match(src("lib/browser-processing/ocr-engine.ts"), new RegExp(`OCR_ENGINE_VERSION = "${pkg.dependencies["tesseract.js"]}"`));
  assert.match(
    src("lib/browser-processing/speech-engine.ts"),
    new RegExp(`SPEECH_ENGINE_VERSION = "${pkg.dependencies["@huggingface/transformers"]}"`),
  );
});

test("when built, every engine file the browser asks for is served by this site", (t) => {
  const manifest = join(ROOT, "public", "engines", "manifest.json");
  if (!existsSync(manifest)) {
    t.skip("public/engines not generated yet (npm run build or npm run dev creates it)");
    return;
  }
  const files = JSON.parse(readFileSync(manifest, "utf8")).files;
  for (const f of [
    "tesseract/worker.min.js",
    "tesseract/core/tesseract-core-simd-lstm.wasm.js",
    "tesseract/lang/eng.traineddata.gz",
    "transformers/transformers.min.js",
    "speech-worker.mjs",
    "ort/ort-wasm-simd-threaded.asyncify.mjs",
    "ort/ort-wasm-simd-threaded.asyncify.wasm",
  ]) {
    assert.ok(files[f] > 0, f);
    assert.ok(existsSync(join(ROOT, "public", "engines", f)), f);
  }
});
