/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        background: '#0F0F13', // Deep dark
        surface: '#18181D', // Slightly lighter dark (Discord style sidebar)
        surfaceHighlight: '#23232A', // Hover state
        primary: '#E91E63', // Pink
        primaryHover: '#C2185B', // Darker pink
        text: '#F2F2F2', // Light text
        textMuted: '#9BA1A6', // Muted text
      }
    },
  },
  plugins: [],
}
