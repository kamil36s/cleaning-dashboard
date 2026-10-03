// Real Edge against the isolated Python test server and generated fixture.
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [url, widthArg, heightArg] = process.argv.slice(2);
if (!url?.startsWith('http://127.0.0.1:')) throw new Error('Isolated loopback URL required');
const width = Number(widthArg);
const height = Number(heightArg);
const edge = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const profile = mkdtempSync(join(tmpdir(), 'language-phase12-edge-'));
const child = spawn(edge, ['--headless=new', '--disable-gpu', '--no-first-run', '--disable-extensions',
  '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
  '--remote-allow-origins=*', '--remote-debugging-port=0', `--window-size=${width},${height}`,
  `--user-data-dir=${profile}`, url], { stdio: 'ignore', windowsHide: true });
const pause = (ms) => new Promise((done) => setTimeout(done, ms));
async function until(fn, message, timeoutMs = 20000) {
  const end = Date.now() + timeoutMs;
  while (Date.now() < end) {
    if (await fn()) return;
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
  await call('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  await until(() => evaluate('!!document.querySelector("#language-view") && document.querySelector("#language-heading")?.textContent === "Overview"'), 'Language shell did not load');
  const routes = ['overview', 'reader', 'vocabulary', 'reviews', 'cloze', 'listening',
    'inbox', 'grammar', 'benchmarks', 'study-session'];
  const results = [];
  for (const route of routes) {
    await evaluate(`location.hash=${JSON.stringify('#' + route)}`);
    await until(() => evaluate(`location.hash===${JSON.stringify('#' + route)} && document.querySelector('#language-view')?.children.length>0`), `${route} did not render`);
    await pause(300);
    const result = await evaluate(`(() => {
      const root=document.querySelector('#language-view');
      const rect=root.getBoundingClientRect();
      const outside=[...root.querySelectorAll('article,section,table,button,input,select')]
        .filter(el=>{const r=el.getBoundingClientRect();return r.width>0 && (r.left<-2 || r.right>innerWidth+2);})
        .slice(0,4).map(el=>el.tagName.toLowerCase()+'.'+el.className);
      return {hash:location.hash, heading:document.querySelector('#language-heading')?.textContent,
        textLength:root.textContent?.trim().length||0, scrollWidth:document.documentElement.scrollWidth,
        width:innerWidth, viewRight:rect.right, outside, buttons:root.querySelectorAll('button').length,
        errorText:root.textContent?.includes('Unable to load')||false};})()`);
    if (result.textLength < 10 || result.scrollWidth > width + 2 || result.viewRight > width + 2 || result.outside.length) {
      throw new Error(`${route} ${width}px layout/content failed: ${JSON.stringify(result)}`);
    }
    results.push({ route, heading: result.heading, errorText: result.errorText });
  }
  const keyboard = await evaluate(`(() => {
    const link=document.querySelector('[data-language-route="reader"]');link.focus();
    return document.activeElement===link && getComputedStyle(link).display!=='none';})()`);
  if (!keyboard) throw new Error('Sidebar link cannot receive keyboard focus');
  console.log(`PASS ${width}x${height}: ${results.length} routes, content bounds, keyboard focus, reduced motion; ${JSON.stringify(results)}`);
} finally {
  socket?.close();
  child.kill();
  for (let attempt = 0; attempt < 10; attempt += 1) {
    await pause(250);
    try { rmSync(profile, { recursive: true, force: true }); break; }
    catch (error) { if (attempt === 9) console.warn(`Edge profile cleanup deferred: ${error.code}`); }
  }
}
