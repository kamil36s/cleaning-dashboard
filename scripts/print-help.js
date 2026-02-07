import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const pkgPath = resolve(__dirname, '..', 'package.json');
const pkg = JSON.parse(readFileSync(pkgPath, 'utf8'));

const descriptions = {
  dev: 'Start Vite dev server (proxy for /gios in dev)',
  'dev:all': 'Run start-dev.cmd (custom dev launcher)',
  build: 'Build production assets to dist/',
  preview: 'Preview production build (no dev proxy)',
  'habits:import': 'Rebuild habits data via Python script',
  test: 'Run tests in watch mode (reruns on file changes)',
  'test:run': 'Run tests once (CI-style)',
  'test:report': 'Generate HTML test report + coverage',
  'test:ui': 'Run Vitest UI in browser',
  'report:open': 'Open HTML test report in browser',
  help: 'Show this help',
};

const order = [
  'dev',
  'dev:all',
  'build',
  'preview',
  'habits:import',
  'test',
  'test:run',
  'test:report',
  'test:ui',
  'report:open',
  'help',
];

const scripts = pkg.scripts || {};
const names = order.filter((name) => scripts[name]);
const maxLen = Math.max(...names.map((n) => n.length), 0);

console.log('Available npm scripts:');
for (const name of names) {
  const pad = ' '.repeat(maxLen - name.length);
  const desc = descriptions[name] || scripts[name];
  console.log(`  npm run ${name}${pad}  - ${desc}`);
}

console.log('\nReports:');
console.log('  Test report:    reports/vitest/index.html');
console.log('  Coverage report: reports/vitest/coverage/index.html');
