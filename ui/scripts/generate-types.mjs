// Generate TypeScript types from the committed OpenAPI snapshots (docs/openapi, written by
// `make openapi`). With --check, fail if the committed output differs from a fresh run: that is
// how "a stale snapshot fails the build" (DESIGN.md section 15.2) is enforced.
import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync, existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const specs = resolve(root, '..', 'docs', 'openapi');
const out = resolve(root, 'src', 'api', 'generated');
const services = ['product-service', 'inventory-service', 'order-service', 'notification-service'];
const check = process.argv.includes('--check');

mkdirSync(out, { recursive: true });
let stale = false;
for (const service of services) {
  const target = resolve(out, `${service}.d.ts`);
  const bin = resolve(root, 'node_modules', '.bin', 'openapi-typescript');
  const generated = execFileSync(bin, [resolve(specs, `${service}.json`)], {
    encoding: 'utf8',
  });
  if (check) {
    if (!existsSync(target) || readFileSync(target, 'utf8') !== generated) {
      console.error(`stale: src/api/generated/${service}.d.ts (run \`make ui-types\`)`);
      stale = true;
    }
  } else {
    writeFileSync(target, generated);
  }
}
process.exit(stale ? 1 : 0);
