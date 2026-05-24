/** @type {import('tailwindcss').Config} */
module.exports = {
    content: [
        "./src/app/**/*.{js,ts,jsx,tsx}",
        "./src/components/**/*.{js,ts,jsx,tsx}",
    ],
    theme: {
        extend: {
            colors: {
                amber: {
                    DEFAULT: "#F59E0B",
                    300: "#FCD34D",
                    400: "#FBBF24",
                    600: "#D97706",
                    800: "#92400E",
                    950: "#1C0A00",
                },
            },
            fontFamily: {
                mono: [
                    '"JetBrains Mono"',
                    '"Fira Code"',
                    '"Cascadia Code"',
                    "ui-monospace",
                    "monospace"
                ],
                // Data: numbers, conditionIds, tickers, CIDs — monospace for
                // alignment of tabular figures (same stack as `mono`).
                data: [
                    '"JetBrains Mono"',
                    '"Fira Code"',
                    '"Cascadia Code"',
                    "ui-monospace",
                    "monospace"
                ],
                // Prose: question text, blockquotes, footer/about copy. A
                // system sans stack (Inter if installed) — no next/font network
                // fetch, so the build stays deterministic and dependency-free.
                prose: [
                    "Inter",
                    "ui-sans-serif",
                    "system-ui",
                    "-apple-system",
                    '"Segoe UI"',
                    "Roboto",
                    '"Helvetica Neue"',
                    "Arial",
                    "sans-serif"
                ],
            },
        },
    },
    plugins: [],
};
