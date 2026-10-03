import { spawn, spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { readFile, writeFile, unlink } from 'node:fs/promises';
import http from 'node:http';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { dirname, join, resolve } from 'node:path';
import process from 'node:process';
import { isCompatibleKermitStatus } from '../js/kermit-contract.js';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const port = 8767;
const statusPath = '/api/kermit/v1/status';
const chatPath = '/api/kermit/v1/chat';
const origin = 'http://127.0.0.1:5173';
const ownerFile = join(tmpdir(), `cleaning-dashboard-kermit-${createHash('sha256').update(root).digest('hex').slice(0, 16)}.json`);
const modelStates = new Set(['sleeping', 'loading', 'ready', 'generating',
  'resource_pressure', 'waiting_for_memory', 'unavailable']);

export function autostartEnabled(value = process.env.KERMIT_AUTOSTART) {
  return !['false', '0', 'no', 'off'].includes(String(value ?? 'true').trim().toLowerCase());
}

export function isKermitStatus(body) {
  return body?.contractVersion === 1 && body.status === 'ok' &&
    body.serviceAvailable === true && typeof body.model === 'string' &&
    modelStates.has(body.modelState) && Array.isArray(body.profiles) &&
    body.profiles.includes('normal') &&
    ['current', 'stale', 'unavailable'].includes(body.index?.state);
}

function probeChat(probePort) {
  return new Promise((resolveProbe) => {
    let settled = false;
    const finish = result => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolveProbe(result);
    };
    const request = http.request({ hostname: '127.0.0.1', port: probePort, path: chatPath,
      method: 'OPTIONS', headers: { Host: `127.0.0.1:${probePort}`, Origin: origin }, agent: false }, response => {
      response.resume();
      response.on('end', () => finish(response.statusCode === 204 &&
        response.headers['access-control-allow-origin'] === origin &&
        String(response.headers['access-control-allow-methods'] || '').split(',').map(x => x.trim()).includes('POST')
        ? { kind: 'supported' }
        : { kind: 'incompatible', reason: 'Kermit restart required: unified chat preflight is unavailable.' }));
    });
    const timeout = setTimeout(() => request.destroy(new Error('chat preflight timeout')), 8500);
    request.on('error', error => finish(error.code === 'ECONNREFUSED' ? { kind: 'vacant' } :
      { kind: 'incompatible', reason: `Kermit restart required: chat preflight failed (${error.message}).` }));
    request.end();
  });
}

function probeStatus(probePort) {
  return new Promise((resolveProbe) => {
    let settled = false;
    let timeout;
    const finish = (result) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      resolveProbe(result);
    };
    const request = http.get({ hostname: '127.0.0.1', port: probePort, path: statusPath,
      headers: { Host: `127.0.0.1:${probePort}`, Origin: origin }, agent: false }, (response) => {
      let raw = '';
      response.setEncoding('utf8');
      response.on('data', (part) => {
        raw += part;
        if (raw.length > 16384) request.destroy(new Error('oversized status response'));
      });
      response.on('end', () => {
        let body;
        try { body = JSON.parse(raw); } catch { body = null; }
        if (response.statusCode === 200 && response.headers['access-control-allow-origin'] === origin && isKermitStatus(body)) {
          finish(isCompatibleKermitStatus(body)
            ? { kind: 'compatible_status', status: body }
            : { kind: 'incompatible', status: body,
              reason: 'Kermit restart required: the running service lacks this dashboard build or chat capability.' });
        } else {
          finish({ kind: 'occupied', reason: 'port 8767 did not return the Kermit v1 status contract' });
        }
      });
    });
    timeout = setTimeout(() => request.destroy(new Error('status timeout')), 8500);
    request.on('error', (error) => finish(error.code === 'ECONNREFUSED'
      ? { kind: 'vacant' }
      : { kind: 'occupied', reason: `port 8767 could not be verified (${error.message})` }));
  });
}

export async function probeKermit(probePort = port) {
  const status = await probeStatus(probePort);
  if (status.kind !== 'compatible_status') return status;
  const chat = await probeChat(probePort);
  return chat.kind === 'supported' ? { kind: 'healthy', status: status.status } :
    { ...chat, status: status.status };
}

function pythonCommand() {
  for (const command of ['python', 'py']) {
    const check = spawnSync(command, ['--version'], { cwd: root, stdio: 'ignore', windowsHide: true });
    if (!check.error && check.status === 0) return command;
  }
  throw new Error('Python was not found in PATH');
}

export function launchKermit({ findPython = pythonCommand, spawnProcess = spawn } = {}) {
  const child = spawnProcess(findPython(), ['-B', '-m', 'kermit_service'], {
    cwd: root,
    env: { ...process.env, KERMIT_SERVICE_HOST: '127.0.0.1', KERMIT_SERVICE_PORT: String(port),
      PYTHONDONTWRITEBYTECODE: '1' },
    detached: true,
    windowsHide: true,
    stdio: 'ignore',
  });
  return new Promise((resolveLaunch, reject) => {
    child.once('error', reject);
    child.once('spawn', () => { child.unref(); resolveLaunch(child); });
  });
}

export async function readOwnership() {
  try {
    const value = JSON.parse(await readFile(ownerFile, 'utf8'));
    return value?.root === root && value.port === port && Number.isSafeInteger(value.pid) &&
      value.pid > 0 && typeof value.instanceId === 'string' && value.instanceId.length >= 16 ? value : null;
  } catch { return null; }
}

export async function recordOwnership(child, status) {
  if (!Number.isSafeInteger(child?.pid) || child.pid <= 0 ||
      child.pid !== status?.processId || typeof status?.instanceId !== 'string' ||
      status.instanceId.length < 16) return false;
  await writeFile(ownerFile, JSON.stringify({ root, port, pid: child.pid,
    instanceId: status.instanceId }), { encoding: 'utf8', mode: 0o600 });
  return true;
}

export function listenerOwnsPort(pid) {
  if (process.platform !== 'win32') return false;
  const check = spawnSync('powershell', ['-NoProfile', '-Command',
    "@(Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8767 -State Listen -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess -Unique) -join ','"],
  { cwd: root, encoding: 'utf8', timeout: 4000, windowsHide: true });
  return !check.error && check.status === 0 &&
    check.stdout.trim().split(',').some(value => Number(value.trim()) === pid);
}

export async function restartOwnedKermit(state, { probe = probeKermit, readOwner = readOwnership,
  killProcess = pid => process.kill(pid, 'SIGTERM'),
  verifyListener = listenerOwnsPort,
  removeOwner = () => unlink(ownerFile),
  sleep = ms => new Promise(resolveSleep => setTimeout(resolveSleep, ms)) } = {}) {
  const owner = await readOwner();
  const status = state?.status;
  if (!owner || owner.pid !== status?.processId || owner.instanceId !== status?.instanceId ||
      owner.pid === process.pid) {
    return { kind: 'unverified', reason: 'Kermit restart required: the existing listener is not verified as launcher-owned.' };
  }
  // Recheck the same listener immediately before stopping the recorded process.
  const confirmed = await probe();
  if (confirmed.kind !== 'incompatible' || confirmed.status?.processId !== owner.pid ||
      confirmed.status?.instanceId !== owner.instanceId || !await verifyListener(owner.pid)) {
    return { kind: 'changed', reason: 'Kermit listener changed during ownership verification.' };
  }
  try { await killProcess(owner.pid); }
  catch (error) { return { kind: 'failed', reason: `Could not stop verified Kermit process: ${error.message}` }; }
  for (let attempt = 0; attempt < 20; attempt++) {
    await sleep(150);
    const current = await probe();
    if (current.kind === 'vacant') {
      try { await removeOwner(); } catch { /* stale record fails closed on the next probe */ }
      return { kind: 'stopped' };
    }
    if (current.status?.instanceId !== owner.instanceId) {
      return { kind: 'changed', reason: 'Another listener claimed the port after the verified process stopped.' };
    }
  }
  return { kind: 'failed', reason: 'Verified Kermit process did not release the port.' };
}

export async function ensureKermit({ enabled = autostartEnabled(), probe = probeKermit,
  launch = launchKermit, sleep = ms => new Promise(resolveSleep => setTimeout(resolveSleep, ms)),
  restartOwned = (state) => restartOwnedKermit(state, { probe, sleep }),
  saveOwnership = recordOwnership, now = Date.now, timeoutMs = 18000 } = {}) {
  if (!enabled) return { kind: 'disabled' };
  let initial = await probe();
  if (initial.kind === 'healthy') return { kind: 'reused', status: initial.status };
  let restarted = false;
  if (initial.kind === 'incompatible') {
    const result = await restartOwned(initial);
    if (result.kind !== 'stopped') return { kind: 'restart_required', reason: result.reason };
    restarted = true;
    initial = await probe();
    if (initial.kind === 'healthy') return { kind: 'reused', status: initial.status };
  }
  if (initial.kind !== 'vacant') return { kind: 'conflict', reason: initial.reason };

  let child;
  try { child = await launch(); }
  catch (error) { return { kind: 'failed', reason: error.message }; }
  const deadline = now() + timeoutMs;
  while (now() < deadline) {
    await sleep(400);
    const state = await probe();
    if (state.kind === 'healthy') {
      if (child.exitCode !== null && child.exitCode !== undefined) return { kind: 'reused', status: state.status };
      let ownershipRecorded = false;
      try { ownershipRecorded = await saveOwnership(child, state.status); } catch { /* service remains usable */ }
      return { kind: restarted ? 'restarted' : 'started', status: state.status, ownershipRecorded };
    }
    if (state.kind === 'occupied' || state.kind === 'incompatible') return {
      kind: state.kind === 'incompatible' ? 'restart_required' : 'conflict', reason: state.reason };
    if (child.exitCode !== null && child.exitCode !== undefined) {
      return { kind: 'failed', reason: `Kermit process exited with code ${child.exitCode}` };
    }
  }
  return { kind: 'failed', reason: `Kermit did not become ready within ${timeoutMs / 1000} seconds` };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const result = await ensureKermit();
    const message = result.kind === 'disabled' ? 'autostart disabled' :
      result.kind === 'reused' ? 'healthy service reused' :
      result.kind === 'started' ? 'service ready' :
      result.kind === 'restarted' ? 'verified launcher-owned service restarted' :
      `${result.kind}: ${result.reason}`;
    process.stdout.write(`[KERMIT] ${message}${result.status ? `; index ${result.status.index.state}; model ${result.status.modelState}` : ''}${result.ownershipRecorded === false ? '; ownership could not be recorded' : ''}\n`);
    if (['failed', 'conflict', 'restart_required'].includes(result.kind)) process.exitCode = 1;
  } catch (error) {
    process.stderr.write(`[KERMIT] startup check failed: ${error.message}\n`);
    process.exitCode = 1;
  }
}
