import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import process from 'node:process';
import {
  extractLogTime,
  formatLogColumns,
  startsTrace,
} from './dev-log-format.js';

const root = resolve(import.meta.dirname, '..');
const serviceName = String(process.argv[2] || '').toLowerCase();
const isWindows = process.platform === 'win32';
const forceColor = Boolean(process.env.FORCE_COLOR && process.env.FORCE_COLOR !== '0');
const useColor = !process.env.NO_COLOR && (process.stdout.isTTY || forceColor);

for (const stream of [process.stdout, process.stderr]) {
  stream.on('error', (error) => {
    if (error?.code !== 'EPIPE') throw error;
  });
}

const services = {
  api: { label: 'API', color: 35, script: resolve(root, 'server.py') },
  network: { label: 'NET', color: 36, script: resolve(root, 'run_network_monitor.py') },
  scale: { label: 'SCALE', color: 33, script: resolve(root, 'scripts', 'scan_ble.py') },
  vite: { label: 'VITE', color: 32 },
};

const service = services[serviceName];
if (!service) {
  process.stderr.write(`Unknown dev service: ${serviceName || '(missing)'}\n`);
  process.exit(2);
}

function findPython() {
  for (const command of ['py', 'python']) {
    const check = spawnSync(command, ['--version'], {
      cwd: root,
      stdio: 'ignore',
      windowsHide: true,
    });
    if (!check.error && check.status === 0) return command;
  }
  throw new Error('Python was not found. Install Python or add py/python to PATH.');
}

function currentTime() {
  return new Intl.DateTimeFormat('en-GB', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date());
}

function prefixStream(stream, target) {
  let pending = '';
  let traceOpen = false;

  function writeLine(line) {
    if (!line) {
      target.write('\n');
      return;
    }
    const parsed = extractLogTime(line);
    const continuation = traceOpen && !parsed.time;
    const time = parsed.time || (continuation ? '' : currentTime());
    target.write(`${formatLogColumns({
      label: service.label,
      colorCode: service.color,
      time,
      message: parsed.message,
      useColor,
    })}\n`);
    traceOpen = parsed.time
      ? startsTrace(parsed.message)
      : traceOpen || startsTrace(parsed.message);
  }

  stream.setEncoding('utf8');
  stream.on('data', (chunk) => {
    pending += chunk;
    const lines = pending.split(/\r\n|\n|\r/);
    pending = lines.pop() ?? '';
    for (const line of lines) writeLine(line);
  });
  stream.on('end', () => {
    if (pending) writeLine(pending);
  });
}

let executable;
let args;
try {
  if (serviceName === 'vite') {
    if (isWindows) {
      executable = process.env.ComSpec || 'cmd.exe';
      args = ['/d', '/s', '/c', 'npm run dev:lan -- --clearScreen=false'];
    } else {
      executable = 'npm';
      args = ['run', 'dev:lan', '--', '--clearScreen=false'];
    }
  } else {
    executable = findPython();
    args = ['-u', service.script];
  }
} catch (error) {
  process.stderr.write(`[${service.label}] ${error.message}\n`);
  process.exit(1);
}

let stopping = false;
let child = null;
let restartTimer = null;
const autoRestart = serviceName === 'api';
const restartDelayMs = 1500;

function launchChild() {
  if (stopping) return;

  if (serviceName === 'vite') {
    try {
      const settingsDir = resolve(root, 'data', 'settings');
      mkdirSync(settingsDir, { recursive: true });
      writeFileSync(resolve(settingsDir, 'dashboard-started-at.txt'), new Date().toISOString(), 'utf8');
    } catch (error) {
      process.stderr.write(`[VITE] Could not record dashboard start time: ${error.message}\n`);
    }
  }

  const launchedChild = spawn(executable, args, {
    cwd: root,
    env: {
      ...process.env,
      FORCE_COLOR: process.env.FORCE_COLOR || '1',
      PYTHONUNBUFFERED: '1',
    },
    stdio: ['ignore', 'pipe', 'pipe'],
    windowsHide: true,
  });
  child = launchedChild;

  prefixStream(launchedChild.stdout, process.stdout);
  prefixStream(launchedChild.stderr, process.stderr);

  launchedChild.on('error', (error) => {
    process.stderr.write(`${formatLogColumns({
      label: service.label,
      colorCode: service.color,
      time: currentTime(),
      message: `Could not start: ${error.message}`,
      useColor,
    })}\n`);
  });

  launchedChild.on('exit', (code, signal) => {
    if (child === launchedChild) child = null;
    if (stopping) {
      process.exitCode = Number.isInteger(code) ? code : 0;
      return;
    }

    const reason = signal ? `signal ${signal}` : `code ${code ?? 'unknown'}`;
    if (autoRestart) {
      process.stderr.write(`${formatLogColumns({
        label: service.label,
        colorCode: service.color,
        time: currentTime(),
        message: `Service stopped (${reason}). Restarting in ${restartDelayMs / 1000}s.`,
        useColor,
      })}\n`);
      restartTimer = setTimeout(() => {
        restartTimer = null;
        launchChild();
      }, restartDelayMs);
      return;
    }

    if (code || signal) {
      process.stderr.write(`${formatLogColumns({
        label: service.label,
        colorCode: service.color,
        time: currentTime(),
        message: `Service stopped (${reason}).`,
        useColor,
      })}\n`);
    }
    process.exitCode = Number.isInteger(code) ? code : signal ? 1 : 0;
  });
}

function stopChild() {
  if (stopping) return;
  stopping = true;
  if (restartTimer) {
    clearTimeout(restartTimer);
    restartTimer = null;
  }
  if (child && !child.killed) child.kill();
}

process.on('SIGINT', stopChild);
process.on('SIGTERM', stopChild);
process.on('SIGHUP', stopChild);

launchChild();
