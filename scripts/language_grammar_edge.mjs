// Exact viewport Edge smoke driver, using Node's built-in WebSocket and CDP.
import { spawn } from 'node:child_process';
import { readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';

const [edge, profile, widthArg, heightArg, url, screenshot, domFile] = process.argv.slice(2);
const browser = spawn(edge, ['--headless', '--disable-gpu', '--disable-background-timer-throttling', '--disable-renderer-backgrounding', '--disable-backgrounding-occluded-windows', '--no-first-run', '--no-default-browser-check', '--remote-debugging-port=0', `--user-data-dir=${profile}`], { windowsHide: true, stdio: 'ignore' });
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));
let socket;
try {
  let port;
  for (let n = 0; n < 100; n++) {
    try { port = (await readFile(path.join(profile, 'DevToolsActivePort'), 'utf8')).split('\n')[0]; break; } catch { await sleep(100); }
  }
  if (!port) throw new Error('Edge debugging port unavailable');
  const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const target = targets.find(item => item.type === 'page');
  socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let sequence = 0; const pending = new Map();
  socket.onmessage = event => {
    const value = JSON.parse(event.data); const entry = pending.get(value.id);
    if (!entry) return;
    pending.delete(value.id); value.error ? entry.reject(new Error(JSON.stringify(value.error))) : entry.resolve(value.result);
  };
  const call = (method, params = {}) => new Promise((resolve, reject) => {
    const id = ++sequence; pending.set(id, { resolve, reject }); socket.send(JSON.stringify({ id, method, params }));
  });
  await call('Emulation.setDeviceMetricsOverride', { width: Number(widthArg), height: Number(heightArg), deviceScaleFactor: 1, mobile: false });
  await call('Page.enable'); await call('Page.navigate', { url });
  let result;
  for (let n = 0; n < 600; n++) {
    const value = await call('Runtime.evaluate', { expression: 'document.querySelector("#result")?.textContent', returnByValue: true });
    const text = value.result?.value;
    if (text?.startsWith('{')) { result = JSON.parse(text); break; }
    await sleep(100);
  }
  if (!result) result = { pass: false, error: 'Browser result timed out' };
  const dimensions = await call('Runtime.evaluate', { expression: 'JSON.stringify({width:innerWidth,height:innerHeight,frameWidth:document.querySelector("iframe")?.contentWindow.innerWidth})', returnByValue: true });
  result.viewport = JSON.parse(dimensions.result.value);
  const dom = await call('Runtime.evaluate', { expression: 'document.documentElement.outerHTML', returnByValue: true });
  await writeFile(domFile, dom.result.value);
  await call('Runtime.evaluate', { expression: 'document.querySelector("iframe")?.contentDocument.querySelector(".language-grammar article")?.scrollIntoView({block:"start"})' });
  await sleep(100);
  const image = await call('Page.captureScreenshot', { format: 'png' }); await writeFile(screenshot, Buffer.from(image.data, 'base64'));
  process.stdout.write(JSON.stringify(result));
} finally {
  socket?.close(); browser.kill();
}
