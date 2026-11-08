/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        slate: {
          50: '#faf9fc', 100: '#f2f0f7', 200: '#e8e5ef', 300: '#d7d3e1',
          400: '#a49db2', 500: '#777185', 600: '#5c566b', 700: '#454054',
          800: '#322d3f', 900: '#241f30', 950: '#18151f',
        },
        zinc: {
          50: '#faf9fc', 100: '#f1eff5', 200: '#e5e1ec', 300: '#cec8d8',
          400: '#a19aac', 500: '#7a7387', 600: '#5d5769', 700: '#45404f',
          800: '#302c38', 900: '#211e28', 950: '#15131b',
        },
        indigo: {
          50: '#f3f1ff', 100: '#e8e4ff', 200: '#d4ceff', 300: '#b8adff',
          400: '#9c8bf4', 500: '#806de3', 600: '#6e5bd1', 700: '#5b4db6',
          800: '#493f91', 900: '#39336e', 950: '#28244d',
        },
        tg: {
          bg: 'var(--tg-theme-bg-color, #f8fafc)',
          text: 'var(--tg-theme-text-color, #0f172a)',
          hint: 'var(--tg-theme-hint-color, #64748b)',
          link: 'var(--tg-theme-link-color, #4f46e5)',
          button: 'var(--tg-theme-button-color, #4f46e5)',
          buttonText: 'var(--tg-theme-button-text-color, #ffffff)',
          secondaryBg: 'var(--tg-theme-secondary-bg-color, #f1f5f9)',
          headerBg: 'var(--tg-theme-header-bg-color, #ffffff)',
          sectionBg: 'var(--tg-theme-section-bg-color, #ffffff)',
          destructive: 'var(--tg-theme-destructive-text-color, #ef4444)',
        },
        calm: {
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          300: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b',
          900: '#0f172a',
          accent: '#6366f1',
          softRose: '#fda4af',
          softAmber: '#fcd34d',
          softEmerald: '#6ee7b7',
        }
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          '"Segoe UI"',
          'Roboto',
          'Helvetica',
          'Arial',
          'sans-serif',
        ],
      },
      animation: {
        'pulse-subtle': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
        'fade-in': 'fadeIn 0.38s ease-out both',
        'slide-up': 'slideUp 0.42s cubic-bezier(0.2, 0.75, 0.25, 1) both',
        'float-soft': 'floatSoft 5s ease-in-out infinite',
        'gradient-drift': 'gradientDrift 12s ease-in-out infinite',
      },
      keyframes: {
        fadeIn: {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        slideUp: {
          '0%': { opacity: '0', transform: 'translateY(16px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        floatSoft: {
          '0%, 100%': { transform: 'translateY(0)' },
          '50%': { transform: 'translateY(-4px)' },
        },
        gradientDrift: {
          '0%, 100%': { backgroundPosition: '0% 50%' },
          '50%': { backgroundPosition: '100% 50%' },
        },
      },
    },
  },
  plugins: [],
}
