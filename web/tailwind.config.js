const c = (name) => `rgb(var(--${name}) / <alpha-value>)`;

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: ["class", '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: c("bg"),
        surface: c("surface"),
        surface2: c("surface2"),
        line: c("line"),
        fg: c("fg"),
        muted: c("muted"),
        accent: c("accent"),
        "accent-fg": c("accent-fg"),
        ok: c("ok"),
        warn: c("warn"),
        err: c("err"),
        info: c("info"),
      },
      fontFamily: {
        sans: ['ui-sans-serif', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      fontSize: { xs: ["0.75rem", "1.05rem"], sm: ["0.8125rem", "1.2rem"] },
      keyframes: {
        pulseDot: { "0%,100%": { opacity: 1 }, "50%": { opacity: 0.35 } },
        blink: { "0%,49%": { opacity: 1 }, "50%,100%": { opacity: 0 } },
        slideIn: { from: { transform: "translateY(8px)", opacity: 0 }, to: { transform: "none", opacity: 1 } },
      },
      animation: {
        pulseDot: "pulseDot 1.4s ease-in-out infinite",
        blink: "blink 1s steps(1) infinite",
        slideIn: "slideIn .18s ease-out",
      },
    },
  },
  plugins: [],
};
