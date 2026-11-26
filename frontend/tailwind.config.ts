import type { Config } from "tailwindcss";

// EvidenceX design language: dark navy/charcoal base with restrained semantic
// accents. amber = potential inconsistency, neutral = unresolved, green = done.
const config: Config = {
  content: [
    "./app/**/*.{ts,tsx}",
    "./components/**/*.{ts,tsx}",
    "./lib/**/*.{ts,tsx}",
  ],
  theme: {
    extend: {
      // System fonts only: nothing is fetched from a font CDN at build or run time.
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "Arial",
          "sans-serif",
        ],
        mono: ["ui-monospace", "SFMono-Regular", "Cascadia Mono", "Consolas", "monospace"],
      },
      colors: {
        navy: {
          950: "#0a0f1a",
          900: "#0e1524",
          850: "#121b2e",
          800: "#172338",
          700: "#1f2f4a",
          600: "#2b3f61",
        },
        charcoal: {
          900: "#14171c",
          800: "#1b1f26",
          700: "#252b35",
        },
        // Semantic accents — use sparingly and only with their intended meaning.
        inconsistency: "#f59e0b", // amber: potential inconsistency / contradiction
        unresolved: "#94a3b8", // neutral slate: unresolved finding
        processed: "#22c55e", // green: completed processing
        failed: "#f87171", // muted red: failed processing (never amber; see steering)
      },
      // Text-only contrast floor on the dark surfaces. Stock slate-500/600 text is
      // ~4.0:1 / ~2.6:1 on navy-950, below WCAG AA (4.5:1) for small text. These lift
      // TEXT colour only (borders, fills and backgrounds keep the stock shades):
      // slate-500 ≈ 5.9:1 and slate-600 ≈ 4.8:1 on navy-950 (≥ 4.5:1 on navy-900).
      textColor: {
        slate: {
          500: "#8794aa",
          600: "#76839a",
        },
      },
    },
  },
  plugins: [],
};

export default config;
