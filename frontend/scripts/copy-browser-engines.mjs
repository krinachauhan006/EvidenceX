// Copies the in-browser engine files from node_modules into public/engines so the
// web app serves them itself (same origin: no CDN, and the CSP stays 'self' for
// scripts). Runs before `next dev` and `next build` (package.json pre-scripts).
// public/engines is generated and git-ignored.
//
//   public/engines/tesseract/worker.min.js            Tesseract.js worker      ~0.1 MB
//   public/engines/tesseract/core/*-lstm.wasm.js      OCR core (one is used)   ~3.9 MB
//   public/engines/tesseract/lang/eng.traineddata.gz  English, LSTM best_int   ~2.9 MB
//   public/engines/transformers/transformers.min.js   Transformers.js browser  ~0.6 MB
//   public/engines/speech-worker.mjs                  Whisper worker (lib/browser-processing)
//   public/engines/ort/ort-wasm-simd-threaded.*       ONNX Runtime WASM        ~27 MB
//
// The speech model weights are NOT copied: the browser downloads them from the
// Hugging Face Hub on first use and keeps them in its cache.

import { copyFileSync, existsSync, mkdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(ROOT, "public", "engines");

/** The installed package directory as Node would find it from `from` (nested first).
 *  Package "exports" maps may hide package.json from require.resolve, so look directly. */
function pkgDir(name, from = ROOT) {
  for (let dir = from; ; dir = dirname(dir)) {
    const candidate = join(dir, "node_modules", name);
    if (existsSync(join(candidate, "package.json"))) return candidate;
    if (dirname(dir) === dir) break;
  }
  console.error(`copy-browser-engines: package ${name} is not installed. Run npm install.`);
  process.exit(1);
}

const tesseract = pkgDir("tesseract.js");
const core = pkgDir("tesseract.js-core", tesseract);
const eng = pkgDir("@tesseract.js-data/eng");
const transformers = pkgDir("@huggingface/transformers");
// The ONNX Runtime build that Transformers.js itself depends on.
const ort = pkgDir("onnxruntime-web", transformers);

// The ONNX Runtime WebAssembly build the Transformers.js bundle loads for CPU (WASM)
// inference.
const ORT_FILES = ["ort-wasm-simd-threaded.asyncify.mjs", "ort-wasm-simd-threaded.asyncify.wasm"];

const files = [
  [join(tesseract, "dist", "worker.min.js"), "tesseract/worker.min.js"],
  ...["tesseract-core-lstm.wasm.js", "tesseract-core-simd-lstm.wasm.js", "tesseract-core-relaxedsimd-lstm.wasm.js"].map(
    (f) => [join(core, f), `tesseract/core/${f}`],
  ),
  [join(eng, "4.0.0_best_int", "eng.traineddata.gz"), "tesseract/lang/eng.traineddata.gz"],
  // Self-contained browser build of Transformers.js (bundles the ONNX Runtime JS) and
  // the worker that runs it. Not bundled by webpack, which cannot build this runtime.
  [join(transformers, "dist", "transformers.min.js"), "transformers/transformers.min.js"],
  [join(ROOT, "lib", "browser-processing", "speech-worker.mjs"), "speech-worker.mjs"],
  ...ORT_FILES.map((f) => [join(ort, "dist", f), `ort/${f}`]),
];

rmSync(OUT, { recursive: true, force: true });
const manifest = { generated_by: "scripts/copy-browser-engines.mjs", versions: {}, files: {} };
for (const name of ["tesseract.js", "@huggingface/transformers"]) {
  manifest.versions[name] = JSON.parse(readFileSync(join(pkgDir(name), "package.json"), "utf8")).version;
}
manifest.versions["tesseract.js-core"] = JSON.parse(readFileSync(join(core, "package.json"), "utf8")).version;
manifest.versions["onnxruntime-web"] = JSON.parse(readFileSync(join(ort, "package.json"), "utf8")).version;

for (const [src, rel] of files) {
  if (!existsSync(src)) {
    console.error(`copy-browser-engines: missing ${src}. Run npm install.`);
    process.exit(1);
  }
  const dest = join(OUT, rel);
  mkdirSync(dirname(dest), { recursive: true });
  copyFileSync(src, dest);
  manifest.files[rel] = statSync(dest).size;
}
writeFileSync(join(OUT, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);
const total = Object.values(manifest.files).reduce((a, b) => a + b, 0);
console.log(`copy-browser-engines: ${files.length} files, ${(total / 1e6).toFixed(1)} MB -> public/engines`);
