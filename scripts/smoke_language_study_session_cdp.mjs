// Browser smoke against the isolated server provided by the Python caller.
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [url, widthArg, heightArg, mode] = process.argv.slice(2);
if (!url?.startsWith('http://127.0.0.1:')) throw new Error('Isolated loopback URL required');
const width = Number(widthArg);
const height = Number(heightArg);
const edge = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const profile = mkdtempSync(join(tmpdir(), 'language-session-edge-'));
const child = spawn(edge, ['--headless=new', '--disable-gpu', '--no-first-run', '--disable-extensions',
  '--remote-allow-origins=*', '--remote-debugging-port=0', `--window-size=${width},${height}`,
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
  const promise = new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
  socket.send(JSON.stringify({ id, method, params }));
  return promise;
}
async function evaluate(expression) {
  const result = await call('Runtime.evaluate', { expression, returnByValue: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || 'Browser evaluation failed');
  return result.result?.value;
}
try {
  const portFile = join(profile, 'DevToolsActivePort');
  await until(() => existsSync(portFile), 'Edge debugging port did not start');
  const port = Number(readFileSync(portFile, 'utf8').split('\n')[0]);
  const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const page = pages.find((entry) => entry.type === 'page');
  if (!page) throw new Error('Edge page missing');
  socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {
    socket.addEventListener('open', resolve, { once: true });
    socket.addEventListener('error', reject, { once: true });
  });
  socket.addEventListener('message', ({ data }) => {
    const message = JSON.parse(data);
    if (!message.id || !pending.has(message.id)) return;
    const item = pending.get(message.id);
    pending.delete(message.id);
    if (message.error) item.reject(new Error(message.error.message));
    else item.resolve(message.result);
  });
  await call('Runtime.enable');
  await call('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 600 });
  await until(() => evaluate('location.hash === "#study-session" && !!document.querySelector("#language-session-minutes")'), 'Builder route did not load');
  for (const minutes of [10, 20, 30]) {
    await evaluate(`(() => { const s=document.querySelector('#language-session-minutes'); s.value='${minutes}'; s.form.requestSubmit(); return true; })()`);
    await until(() => evaluate(`document.querySelector('.language-session-builder')?.textContent.includes('${minutes} min requested')`), `Missing ${minutes}-minute plan`);
    const result = await evaluate(`(() => {
      const cards=[...document.querySelectorAll('.language-session-card')];
      const bad=cards.some(c=>{const r=c.getBoundingClientRect(); return r.left<0 || r.right>innerWidth+2;});
      return { overflow: document.documentElement.scrollWidth>innerWidth+2 || bad,
        cards: cards.length, text: document.querySelector('.language-session-builder').textContent,
        first: cards[0]?.querySelector('a')?.getAttribute('href') }; })()`);
    if (result.overflow) throw new Error(`${width}px layout overflow`);
    if (mode === 'empty' && (result.cards || !result.text.includes('No useful study work'))) throw new Error('Empty state is dishonest');
    if (mode === 'populated' && (!result.cards || !result.text.includes('Source:') || !result.text.includes('min'))) throw new Error('Segments incomplete');
    if (mode === 'populated' && minutes === 20) {
      await evaluate('document.querySelector(".language-session-card a").click()');
      await until(() => evaluate(`location.hash === ${JSON.stringify(result.first)}`), 'Destination handoff failed');
      await evaluate('location.hash="#study-session"');
      await until(() => evaluate('!!document.querySelector("#language-session-minutes")'), 'Builder return failed');
    }
  }
  console.log(`PASS ${width}x${height} ${mode}: route, durations, plan, navigation, bounds`);
} finally {
  socket?.close();
  child.kill();
  for (let attempt = 0; attempt < 10; attempt += 1) {
    await pause(250);
    try { rmSync(profile, { recursive: true, force: true }); break; }
    catch (error) { if (attempt === 9) console.warn(`Edge profile cleanup deferred: ${error.code}`); }
  }
}
