import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        obsidian: "#F8FAFC", // Light Slate-50 background
        gunmetal: "#FFFFFF", // Pure white card/bubble background
        critical: "#DC2626", // Readable red-600
        oracle: "#0284C7",   // Readable sky-600
        pass: "#059669",     // Readable emerald-600
        evergreen: '#0C5A4C', // Deep rich teal-green accent
        mist: '#0F172A',     // Charcoal slate-900 text color
        void: '#E2E8F0'      // Light slate-200 border color
      },
      fontFamily: {
        sans: ['Inter', 'Geist', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        serif: ['Playfair Display', 'Georgia', 'ui-serif', 'serif'],
      },
      letterSpacing: {
        tight: '-0.015em',
        tighter: '-0.03em',
        tightest: '-0.05em',
      }
    },
  },
  plugins: [],
};
export default config;
