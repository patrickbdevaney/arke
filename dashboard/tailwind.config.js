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
            },
        },
    },
    plugins: [],
};
