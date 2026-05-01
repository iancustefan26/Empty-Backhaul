/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        sentry: "#22d3ee",
        analyst: "#a78bfa",
        strategist: "#f59e0b",
        documents: "#34d399",
      },
    },
  },
  plugins: [],
};
