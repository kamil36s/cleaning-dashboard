import { existsSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawn } from 'node:child_process';
import http from 'node:http';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const root = resolve(__dirname, '..');
const reportPath = resolve(root, 'reports', 'vitest', 'index.html');

if (!existsSync(reportPath)) {
  console.error('Report not found. Run: npm run test:report');
  process.exit(1);
}

const port = process.env.REPORT_PORT || '4173';
const url = `http://localhost:${port}`;

console.log(`Starting report server at ${url}`);

const server = spawn(`npx vite preview --outDir reports/vitest --port ${port}`, {
  stdio: 'inherit',
  shell: true,
});

const waitForServer = (targetUrl, timeoutMs = 8000, intervalMs = 250) =>
  new Promise((resolve) => {
    const start = Date.now();
    const attempt = () => {
      const req = http.get(targetUrl, (res) => {
        res.resume();
        resolve(true);
      });
      req.on('error', () => {
        if (Date.now() - start >= timeoutMs) {
          resolve(false);
          return;
        }
        setTimeout(attempt, intervalMs);
      });
    };
    attempt();
  });

(async () => {
  const ready = await waitForServer(url);
  if (!ready) {
    console.warn('Server is taking longer than expected. Opening report anyway...');
  }
  const openCmd = process.platform === 'win32'
    ? `start "" "${url}"`
    : process.platform === 'darwin'
      ? `open "${url}"`
      : `xdg-open "${url}"`;
  spawn(openCmd, { stdio: 'ignore', shell: true });
})();

server.on('exit', (code) => {
  process.exit(code ?? 0);
});
