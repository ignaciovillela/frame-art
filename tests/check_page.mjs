// Comprueba que los <script> de app/page.html compilan (sintaxis). Es lo único de la interfaz que ninguna prueba en Python alcanza:
// un error ahí deja la página en blanco. Uso: node tests/check_page.mjs
import { readFileSync } from 'node:fs';
const html = readFileSync(new URL('../app/page.html', import.meta.url), 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
if (!scripts.length) throw new Error('page.html no tiene ningún <script>');
scripts.forEach((code, i) => {
  try { new Function(code); } catch (e) { console.error(`script #${i + 1}: ${e.message}`); process.exit(1); }
});
console.log(`page.html: ${scripts.length} scripts compilan`);
