import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        border: "hsl(214 20% 88%)",
        background: "hsl(210 20% 98%)",
        foreground: "hsl(216 28% 14%)",
        muted: "hsl(215 16% 47%)",
        panel: "hsl(0 0% 100%)",
        primary: "hsl(212 92% 42%)",
      },
      borderRadius: {
        lg: "8px",
      },
    },
  },
  plugins: [],
} satisfies Config;
