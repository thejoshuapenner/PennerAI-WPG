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
        obsidian: "#0B0D14",
        gunmetal: "#161922",
        critical: "#E11D48",
        oracle: "#38BDF8",
        pass: "#10B981",
        evergreen: '#004D40',
        mist: '#f8fafc',
        void: '#0f172a'
      },
      fontFamily: {
        sans: ['Geist', 'Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
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
