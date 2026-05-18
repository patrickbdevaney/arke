/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx}",
    "./src/components/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        bg: "#0a0a0a",
        panel: "#111111",
        border: "#1f1f1f",
        amber: {
          DEFAULT: "#ffb347",
          dim: "#b87a30",
        },
        terminal: {
          green: "#22c55e",
          red: "#ef4444",
          muted: "#666666",
        },
      },
      fontFamily: {
        mono: ['"JetBrains Mono"', '"Fira Code"', "ui-monospace", "monospace"],
      },
    },
  },
  plugins: [],
};
