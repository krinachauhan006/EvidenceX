// Whisper speech recognition (Transformers.js) in a module Web Worker, so the page
// stays responsive. This file is NOT bundled: scripts/copy-browser-engines.mjs copies
// it to public/engines/speech-worker.mjs next to the self-contained browser build of
// Transformers.js (public/engines/transformers/transformers.min.js) and the ONNX
// Runtime WebAssembly files (public/engines/ort/), all served by this web app.
//
// Only the MODEL WEIGHTS are downloaded (from the Hugging Face Hub, then kept in the
// browser's Cache Storage). The recording is passed in as samples by the page and
// never leaves this device: this worker makes no request with it.

import { env, pipeline } from "./transformers/transformers.min.js";

let transcriber = null;

function load(model) {
  if (!transcriber) {
    env.allowLocalModels = false;
    env.useBrowserCache = true;
    const wasm = env.backends?.onnx?.wasm;
    if (wasm) {
      wasm.wasmPaths = new URL("./ort/", self.location.href).href;
      // Threads need cross-origin isolation, which this site does not enable.
      wasm.numThreads = 1;
    }
    transcriber = pipeline("automatic-speech-recognition", model, {
      device: "wasm",
      dtype: "q8", // ~41 MB: encoder 10 MB + merged decoder 31 MB
      progress_callback: (p) => {
        if (p && p.status === "progress" && typeof p.loaded === "number") {
          self.postMessage({
            type: "progress",
            stage: "loading",
            file: String(p.file ?? ""),
            loaded: p.loaded,
            total: typeof p.total === "number" ? p.total : null,
          });
        }
      },
    });
    transcriber.catch(() => {
      transcriber = null;
    });
  }
  return transcriber;
}

self.onmessage = async (event) => {
  const msg = event.data;
  if (!msg || msg.type !== "transcribe") return;
  try {
    const run = await load(msg.model);
    self.postMessage({ type: "progress", stage: "transcribing" });
    const out = await run(msg.audio, {
      chunk_length_s: 30,
      stride_length_s: 5,
      return_timestamps: true,
      task: "transcribe",
      // Stated explicitly (and recorded on the run): without it Transformers.js
      // silently assumes English.
      language: msg.language,
    });
    self.postMessage({ type: "result", chunks: out?.chunks ?? [] });
  } catch (err) {
    const message = err instanceof Error ? err.message : String(err);
    // The engine's message only; never evidence content.
    self.postMessage({ type: "error", message: message.slice(0, 300), range: err instanceof RangeError });
  }
};
