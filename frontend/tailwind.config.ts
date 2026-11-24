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
    },
  },
  plugins: [],
};

export default config;
