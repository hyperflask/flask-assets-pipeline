/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    ...process.env.TAILWIND_CONTENT.split(';'),
    // your content entries here
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}