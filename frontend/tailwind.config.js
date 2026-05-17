/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // semantic tokens — actual values live as CSS vars in index.css
        background: "rgb(var(--rgb-background) / <alpha-value>)",
        foreground: "rgb(var(--rgb-foreground) / <alpha-value>)",
        card: "rgb(var(--rgb-card) / <alpha-value>)",
        "card-foreground": "rgb(var(--rgb-card-foreground) / <alpha-value>)",
        border: "rgb(var(--rgb-border) / <alpha-value>)",
        muted: "rgb(var(--rgb-muted) / <alpha-value>)",
        "muted-foreground": "rgb(var(--rgb-muted-foreground) / <alpha-value>)",
        primary: "rgb(var(--rgb-primary) / <alpha-value>)",
        "primary-foreground": "rgb(var(--rgb-primary-foreground) / <alpha-value>)",
        destructive: "rgb(var(--rgb-destructive) / <alpha-value>)",
        "destructive-foreground": "rgb(var(--rgb-destructive-foreground) / <alpha-value>)",
        "surface-1": "rgb(var(--rgb-surface-1) / <alpha-value>)",
        "surface-2": "rgb(var(--rgb-surface-2) / <alpha-value>)",
        depot: "rgb(var(--rgb-depot) / <alpha-value>)",
        good: "rgb(var(--rgb-good) / <alpha-value>)",
        warn: "rgb(var(--rgb-warn) / <alpha-value>)",
        customer: "rgb(var(--rgb-customer) / <alpha-value>)",
        broker: "rgb(var(--rgb-broker) / <alpha-value>)",
        accent: "rgb(var(--rgb-accent) / <alpha-value>)",
        // legacy agent palette (kept for backward compat with leftover bits)
        sentry: "#22d3ee",
        analyst: "#a78bfa",
        strategist: "#f59e0b",
        documents: "#34d399",
      },
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
      },
      borderRadius: {
        sm: "calc(var(--radius) - 4px)",
        md: "calc(var(--radius) - 2px)",
        lg: "var(--radius)",
        xl: "calc(var(--radius) + 4px)",
      },
    },
  },
  plugins: [],
};
