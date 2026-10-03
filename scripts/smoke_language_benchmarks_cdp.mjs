// Browser-only smoke. The caller supplies an isolated HTTP fixture URL.
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve, sep } from 'node:path';

const edge = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const url = process.argv[2];
if (!url?.startsWith('http://127.0.0.1:')) throw new Error('Isolated loopback URL required');
const profile = mkdtempSync(join(tmpdir(), 'language-benchmark-edge-'));
const child = spawn(edge, ['--headless=new', '--disable-gpu', '--no-first-run', '--disable-extensions',
  '--remote-allow-origins=*', '--remote-debugging-port=0', '--window-size=390,844',
  `--user-data-dir=${profile}`, url], { stdio: 'ignore', windowsHide: true });

const pause = (ms) => new Promise((done) => setTimeout(done, ms));
async function until(fn, message, timeoutMs = 20000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    const value = await fn();
    if (value) return value;
    await pause(100);
  }
  throw new Error(message);
}

let socket;
let counter = 0;
const pending = new Map();
async function call(method, params = {}) {
  const id = ++counter;
  const promise = new Promise((resolveResult, reject) => pending.set(id, { resolveResult, reject }));
  socket.send(JSON.stringify({ id, method, params }));
  return promise;
}
async function evaluate(expression) {
  const result = await call('Runtime.evaluate', { expression, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || 'Browser expression failed');
  return result.result?.value;
}

try {
  const portFile = join(profile, 'DevToolsActivePort');
  await until(() => existsSync(portFile), 'Edge debugging port did not start');
  const port = Number(readFileSync(portFile, 'utf8').split('\n')[0]);
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = pages.find((entry) => entry.type === 'page');
  if (!page) throw new Error('Edge page was not found');
  socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolveOpen, reject) => {
    socket.addEventListener('open', resolveOpen, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  socket.addEventListener('message', ({ data }) => {
    const message = JSON.parse(data);
    if (!message.id || !pending.has(message.id)) return;
    const item = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) item.reject(new Error(message.error.message));
    else item.resolveResult(message.result);
  });
  await call('Runtime.enable');
  await until(() => evaluate('document.body?.textContent.includes("Norway Preparation")'), 'Benchmark landing did not load');
  if (await evaluate('document.documentElement.scrollWidth > innerWidth + 2')) throw new Error('Landing overflows at 390 px');
  await evaluate('([...document.querySelectorAll("button")].find(b => b.textContent.includes("Start benchmark"))).click()');
  await until(() => evaluate('location.hash.startsWith("#benchmarks/run/") && !!document.querySelector(".language-benchmark-progress")'), 'Run did not start');
  if (await evaluate('document.documentElement.scrollWidth > innerWidth + 2')) throw new Error('Runner overflows at 390 px');
  const sections = new Set();
  for (let index = 0; index < 16; index += 1) {
    const section = await evaluate('document.querySelector(".language-benchmark-question h4")?.textContent');
    if (!section) throw new Error(`Missing section at item ${index + 1}`);
    sections.add(section);
    const action = await evaluate(`(() => {
      const form = document.querySelector('.language-benchmark-question');
      const skip = [...form.querySelectorAll('button')].find(b => b.textContent.includes('Mark Listening unavailable'));
      if (skip) { skip.click(); return 'skipped'; }
      const play = [...form.querySelectorAll('button')].find(b => b.textContent.includes('Play audio'));
      if (play) play.click();
      const input = form.querySelector('input,select');
      input.value = input.tagName === 'SELECT' ? input.options[1].value : 'x';
      form.requestSubmit();
      return 'answered';
    })()`);
    if (!action) throw new Error('Item action failed');
    await until(() => evaluate(`document.querySelector('.language-benchmark-progress')?.textContent.includes('${index + 1} / 16 answered')`),
      `Item ${index + 1} did not persist`);
  }
  if (sections.size !== 4) throw new Error(`Expected four sections, got ${[...sections].join(', ')}`);
  await evaluate('([...document.querySelectorAll("button")].find(b => b.textContent.includes("Finish and score"))).click()');
  await until(() => evaluate('document.body?.textContent.includes("Vocabulary recognition:") && !document.querySelector(".language-benchmark-progress")'),
    'Results did not load');
  if (await evaluate('document.documentElement.scrollWidth > innerWidth + 2')) throw new Error('Results overflow at 390 px');
  const resultText = await evaluate('document.querySelector(".language-benchmark-card")?.textContent');
  for (const label of sections) if (!resultText.includes(label)) throw new Error(`Missing result: ${label}`);
  if (/Norway readiness\s*[:=]\s*\d/i.test(resultText)) throw new Error('Unexpected composite readiness score');
  await evaluate('location.hash = "#benchmarks"');
  await until(() => evaluate('document.body?.textContent.includes("BASELINE · COMPLETED")'), 'Baseline history did not load');
  await evaluate('([...document.querySelectorAll("button")].find(b => b.textContent.includes("Start benchmark"))).click()');
  await until(() => evaluate('location.hash.startsWith("#benchmarks/run/") && document.querySelector(".language-benchmark-card h3")?.textContent.includes("CHECKPOINT · FORM_B")'),
    'Checkpoint did not start');
  console.log('PASS: Edge UI start, 16 saved items, four sections, results, history, checkpoint at 390x844');
} finally {
  socket?.close();
  child.kill();
  const root = resolve(tmpdir()) + sep;
  if (resolve(profile).startsWith(root)) {
    await pause(300);
    try { rmSync(profile, { recursive: true, force: true }); } catch { /* Edge may release its profile shortly after exit. */ }
  }
}
