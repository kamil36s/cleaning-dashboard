// Real Edge screenshots and interaction smoke against the isolated Python fixture.
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, existsSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const [url, widthArg, heightArg, output] = process.argv.slice(2);
if (!url?.startsWith('http://127.0.0.1:')) throw new Error('Isolated loopback URL required');
const width = Number(widthArg);
const height = Number(heightArg);
const edge = 'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe';
const profile = mkdtempSync(join(tmpdir(), 'language-productization-edge-'));
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
  const result = await call('Runtime.evaluate', { expression, returnByValue: true, awaitPromise: true });
  if (result.exceptionDetails) throw new Error(result.exceptionDetails.text || 'Browser evaluation failed');
  return result.result?.value;
}
async function screenshot(name) {
  const result = await call('Page.captureScreenshot', { format: 'png', captureBeyondViewport: false });
  writeFileSync(join(output, `${width}x${height}-${name}.png`), Buffer.from(result.data, 'base64'));
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
  await call('Page.enable');
  await call('Emulation.setDeviceMetricsOverride', { width, height, deviceScaleFactor: 1, mobile: width < 600 });
  await call('Emulation.setEmulatedMedia', { features: [{ name: 'prefers-reduced-motion', value: 'reduce' }] });
  await until(() => evaluate('document.querySelector("#language-heading")?.textContent === "Today" && !!document.querySelector(".language-today-hero")'), 'Language Today did not load');
  const initialLoadMs = Math.round(await evaluate('performance.now()'));
  if (width < 700) {
    const mobileNav = await evaluate(`(() => {
      const button=document.querySelector('#language-mobile-nav');button.click();
      const open=button.getAttribute('aria-expanded')==='true' && getComputedStyle(document.querySelector('#language-section-nav')).display!=='none';
      document.querySelector('[data-language-route="overview"]').click();
      return {open,closed:button.getAttribute('aria-expanded')==='false'};
    })()`);
    if (!mobileNav.open || !mobileNav.closed) throw new Error(`Mobile navigation: ${JSON.stringify(mobileNav)}`);
  }
  const routes = ['overview', 'progress', 'benchmarks', 'study-session', 'curriculum', 'inbox',
    'reader', 'vocabulary', 'phrasebook', 'reviews', 'cloze', 'generate', 'listening',
    'grammar', 'statistics', 'goals', 'settings', 'topics', 'reader/text/000000000000000000000000000186a1'];
  const results = [];
  let readerInitMs = null;
  for (const route of routes) {
    const routeStarted = await evaluate('performance.now()');
    await evaluate(`location.hash=${JSON.stringify('#' + route)}`);
    await until(() => evaluate(`location.hash===${JSON.stringify('#' + route)} && document.querySelector('#language-view')?.children.length>0 && !document.querySelector('#language-view')?.textContent?.startsWith('Loading Language')`), `${route} did not render`);
    await pause(320);
    if (route.startsWith('reader/text/')) {
      await until(() => evaluate('document.querySelectorAll(".language-reader-token[data-token-id]").length >= 8'), 'Reader tokens did not initialize');
      readerInitMs = Math.round((await evaluate('performance.now()')) - routeStarted);
    }
    const result = await evaluate(`(() => {
      const root=document.querySelector('#language-view');
      const outside=[...root.querySelectorAll('article,section,table,button,input,select')]
        .filter(el=>{const r=el.getBoundingClientRect();return r.width>0 && (r.left<-2 || r.right>innerWidth+2);})
        .slice(0,4).map(el=>el.tagName.toLowerCase()+'.'+el.className);
      return {hash:location.hash, heading:document.querySelector('#language-heading')?.textContent,
        textLength:root.textContent?.trim().length||0, scrollWidth:document.documentElement.scrollWidth,
        width:innerWidth, outside, errorText:root.textContent?.includes('Unable to load')||false};})()`);
    if (result.textLength < 10 || result.scrollWidth > width + 2 || result.outside.length) {
      throw new Error(`${route} ${width}px layout/content failed: ${JSON.stringify(result)}`);
    }
    await screenshot(route.replaceAll('/', '-'));
    results.push(result);
  }
  const readerKeyboard = await evaluate(`(() => {
    const words=[...document.querySelectorAll('.language-reader-token[data-token-id]')];
    if (words.length<8) return {error:'reader words missing', count:words.length};
    words[0].focus();
    const first=document.activeElement===words[0];
    words[0].dispatchEvent(new KeyboardEvent('keydown',{key:'ArrowRight',bubbles:true}));
    const next=document.activeElement===words[1];
    const firstLemma=words[0].dataset.lemmaId;
    words[0].focus();
    words[0].dispatchEvent(new KeyboardEvent('keydown',{key:'3',bubbles:true}));
    return {first,next,firstLemma,wordCount:words.length};})()`);
  await until(() => evaluate(`(() => {
    const repeated=[...document.querySelectorAll('.language-reader-token[data-lemma-id]')]
      .filter(word=>word.dataset.lemmaId===${JSON.stringify(readerKeyboard.firstLemma)});
    return repeated.length>=2 && repeated.every(word=>word.classList.contains('is-known'));
  })()`), 'Repeated lemma status did not update');
  await evaluate(`document.querySelectorAll('.language-reader-token[data-token-id]')[1].click()`);
  await until(() => evaluate('!!document.querySelector(".language-word-panel[open]")'), 'Reader compact panel did not open');
  const readerFlow = { ...readerKeyboard, repeatedUpdated: true, panel: true };
  if (!readerFlow.first || !readerFlow.next || !readerFlow.panel || !readerFlow.repeatedUpdated) throw new Error(`Reader flow: ${JSON.stringify(readerFlow)}`);
  await screenshot('reader-word-panel');
  await evaluate(`(() => {
    [...document.querySelectorAll('.language-word-panel button')].find(button=>button.textContent==='Close')?.click();
    document.querySelectorAll('.language-reader-token[data-token-id]')[2]
      .dispatchEvent(new PointerEvent('pointerover',{bubbles:true}));
  })()`);
  await until(() => evaluate('!!document.querySelector(".language-word-quick")'), 'Reader hover meaning did not appear');
  await screenshot('reader-hover');
  const hoverCalls = await evaluate(`(() => {
    const word=document.querySelectorAll('.language-reader-token[data-token-id]')[2];
    const count=()=>performance.getEntriesByType('resource').filter(entry=>entry.name.includes('/preview')).length;
    const first=count();
    word.dispatchEvent(new PointerEvent('pointerout',{bubbles:true}));
    word.dispatchEvent(new PointerEvent('pointerover',{bubbles:true}));
    return new Promise(done=>setTimeout(()=>done({first,second:count()}),450));
  })()`);
  if (hoverCalls.second !== hoverCalls.first) throw new Error(`Hover cache: ${JSON.stringify(hoverCalls)}`);
  await evaluate(`(() => {
    const word=document.querySelectorAll('.language-reader-token[data-token-id]')[1];
    word.click();
  })()`);
  await until(() => evaluate('!!document.querySelector(".language-word-panel[open]")'), 'Reader panel did not reopen');
  await evaluate(`[...document.querySelectorAll('.language-word-panel button')]
    .find(button=>button.textContent==='Open full details')?.click()`);
  await until(() => evaluate('!!document.querySelector("#language-lemma-dialog[open]")'), 'Advanced lexical detail did not open');
  await screenshot('reader-full-detail');
  await evaluate(`document.querySelector('[data-language-dialog-close]')?.click()`);
  if (width < 700) {
    await evaluate(`document.querySelectorAll('.language-reader-token[data-token-id]')[3].click()`);
    await until(() => evaluate('!!document.querySelector(".language-word-panel[open]")'), 'Mobile word sheet did not open');
    await evaluate(`[...document.querySelectorAll('.language-word-panel button')]
      .find(button=>button.textContent==='3 Known')?.click()`);
    await until(() => evaluate('!document.querySelector(".language-word-panel[open]")'), 'Mobile word sheet did not close after save');
    const mobileSaved = await evaluate('document.querySelectorAll(".language-reader-token[data-token-id]")[3].classList.contains("is-known")');
    if (!mobileSaved) throw new Error('Mobile word update was not visible');
  }
  await call('Page.navigate', { url: url.replace('/language.html#overview', '/index.html') });
  await pause(1500);
  const dashboardWidget = await evaluate(`(async () => {
    const card=document.querySelector('[data-widget="language-learning"]');
    if (!card) return {missing:true};
    // The isolated server can inherit the owner's cleaning gate and saved widget settings.
    // Clear those unrelated fixture constraints to inspect the actual Language card.
    document.body.classList.remove('is-cleaning-locked');
    document.querySelector('.dash')?.setAttribute('data-cleaning-locked','false');
    card.hidden=false;
    await import('/js/widget-language-learning.js');
    card.scrollIntoView({block:'center'});
    return {hidden:card.hidden, text:card.textContent?.slice(0,120)};
  })()`);
  if (dashboardWidget.missing || dashboardWidget.hidden) throw new Error(`Dashboard widget: ${JSON.stringify(dashboardWidget)}`);
  await pause(800);
  const widgetAtCapture = await evaluate(`(() => {
    const card=document.querySelector('[data-widget="language-learning"]');
    document.body.classList.remove('is-cleaning-locked');
    document.querySelector('.dash')?.setAttribute('data-cleaning-locked','false');
    card.hidden=false;
    card.scrollIntoView({block:'center'});
    const rect=card.getBoundingClientRect();
    return {hidden:card.hidden,display:getComputedStyle(card).display,top:rect.top,bottom:rect.bottom,
      height:rect.height,body:card.querySelector('.language-learning-widget-body')?.textContent?.slice(0,100)};
  })()`);
  if (widgetAtCapture.height < 100 || widgetAtCapture.top > height) throw new Error(`Widget capture: ${JSON.stringify(widgetAtCapture)}`);
  await screenshot('dashboard-widget');
  console.log(JSON.stringify({ width, height, routes: results.length, initialLoadMs, readerInitMs, readerFlow, hoverCalls,
    errors: results.filter((item) => item.errorText).map((item) => item.hash),
    maxScrollWidth: Math.max(...results.map((item) => item.scrollWidth)), widgetAtCapture }));
} finally {
  socket?.close();
  child.kill();
  for (let attempt = 0; attempt < 10; attempt += 1) {
    await pause(250);
    try { rmSync(profile, { recursive: true, force: true }); break; }
    catch (error) { if (attempt === 9) console.warn(`Edge profile cleanup deferred: ${error.code}`); }
  }
}
