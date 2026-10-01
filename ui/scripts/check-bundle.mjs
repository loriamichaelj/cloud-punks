// Fail the build if the initial JavaScript exceeds 200 kB gzipped (DESIGN.md section 15.5).
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { gzipSync } from 'node:zlib';

const BUDGET_BYTES = 200 * 1000;
const dist = resolve(dirname(fileURLToPath(import.meta.url)), '..', 'dist');
const html = readFileSync(resolve(dist, 'index.html'), 'utf8');
const scripts = [
  ...html.matchAll(/<(?:script|link)[^>]+(?:src|href)="\/(assets\/[^"]+\.js)"/g),
].map((m) => m[1]);
if (scripts.length === 0) {
  console.error('no initial script found in dist/index.html');
  process.exit(1);
}
let total = 0;
for (const file of scripts) total += gzipSync(readFileSync(resolve(dist, file))).length;
console.log(
  `initial JS: ${(total / 1000).toFixed(1)} kB gzipped (budget ${BUDGET_BYTES / 1000} kB)`,
);
if (total > BUDGET_BYTES) {
  console.error('bundle budget exceeded');
  process.exit(1);
}
