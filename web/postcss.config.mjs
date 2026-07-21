// Tailwind v4 handles vendor prefixing internally via Lightning CSS, so the
// separate autoprefixer step v3 required is no longer needed.
const config = { plugins: { "@tailwindcss/postcss": {} } };

export default config;
