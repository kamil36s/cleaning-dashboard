import { describe, expect, it, vi } from 'vitest';
import { EventEmitter } from 'node:events';
import http from 'node:http';
import { autostartEnabled, ensureKermit, isKermitStatus,
  launchKermit, probeKermit, restartOwnedKermit } from '../scripts/kermit-autostart.js';
import { KERMIT_SERVICE_BUILD, KERMIT_CHAT_CAPABILITY } from '../js/kermit-contract.js';

const status = { contractVersion: 1, status: 'ok', serviceAvailable: true,
  serviceBuild: KERMIT_SERVICE_BUILD, capabilities: [KERMIT_CHAT_CAPABILITY],
  instanceId: 'test-instance-123456789', processId: 123,
  model: 'qwen3.5:4b', modelState: 'sleeping', profiles: ['quick', 'normal'],
  index: { state: 'current', buildId: 'test-build' } };
const healthy = { kind: 'healthy', status };
const vacant = { kind: 'vacant' };
const testClock = () => {
  let time = 0;
  return { now: () => time, sleep: vi.fn(async ms => { time += ms; }) };
};

describe('Kermit dashboard autostart', () => {
  it('validates the Kermit status identity, including a stale index and sleeping model', () => {
    expect(isKermitStatus(status)).toBe(true);
    expect(isKermitStatus({ ...status, index: { state: 'stale' } })).toBe(true);
    expect(isKermitStatus({ ...status, contractVersion: 2 })).toBe(false);
    expect(isKermitStatus({ ...status, serviceAvailable: false })).toBe(false);
    expect(isKermitStatus({ ...status, modelState: 'made-up' })).toBe(false);
    expect(isKermitStatus({ ...status, index: {} })).toBe(false);
  });

  it('respects an explicit opt-out without probing or changing dashboard startup', async () => {
    for (const value of ['false', '0', 'no', 'off']) expect(autostartEnabled(value)).toBe(false);
    expect(autostartEnabled()).toBe(true);
    const probe = vi.fn();
    const launch = vi.fn();
    expect(await ensureKermit({ enabled: false, probe, launch })).toEqual({ kind: 'disabled' });
    expect(probe).not.toHaveBeenCalled();
    expect(launch).not.toHaveBeenCalled();
  });

  it('reuses healthy manual or prior dashboard service without process ownership', async () => {
    const launch = vi.fn();
    const probe = vi.fn().mockResolvedValue(healthy);
    for (let attempt = 0; attempt < 2; attempt++) {
      expect(await ensureKermit({ probe, launch })).toEqual({ kind: 'reused', status });
    }
    expect(launch).not.toHaveBeenCalled();
  });

  it('keeps Kermit available when Ollama is unavailable or the index is stale', async () => {
    const degraded = { ...status, providerAvailable: false, modelState: 'unavailable',
      index: { state: 'stale', buildId: 'old-build' } };
    const launch = vi.fn();
    expect(await ensureKermit({ probe: async () => ({ kind: 'healthy', status: degraded }), launch }))
      .toEqual({ kind: 'reused', status: degraded });
    expect(launch).not.toHaveBeenCalled();
  });

  it('starts once, waits for readiness, and leaves a spawned service alive', async () => {
    const clock = testClock();
    const child = { pid: 123, exitCode: null };
    const launch = vi.fn().mockResolvedValue(child);
    const probe = vi.fn().mockResolvedValueOnce(vacant).mockResolvedValueOnce(vacant)
      .mockResolvedValueOnce(healthy);
    const saveOwnership = vi.fn().mockResolvedValue(true);
    expect(await ensureKermit({ ...clock, probe, launch, saveOwnership })).toEqual({ kind: 'started', status, ownershipRecorded: true });
    expect(launch).toHaveBeenCalledTimes(1);
    expect(probe).toHaveBeenCalledTimes(3);
    expect(child.exitCode).toBeNull();
    expect(saveOwnership).toHaveBeenCalledWith(child, status);
  });

  it('recognizes an old healthy /status as incompatible without stopping an unverified listener', async () => {
    const old = { ...status, serviceBuild: undefined, capabilities: undefined,
      instanceId: undefined, processId: undefined };
    const launch = vi.fn();
    const restartOwned = vi.fn().mockResolvedValue({ kind: 'unverified', reason: 'Kermit restart required: unverified listener.' });
    const result = await ensureKermit({ probe: async () => ({ kind: 'incompatible', status: old,
      reason: 'Kermit restart required: the running service lacks unified chat.' }), launch, restartOwned });
    expect(result).toEqual({ kind: 'restart_required', reason: 'Kermit restart required: unverified listener.' });
    expect(launch).not.toHaveBeenCalled();
  });

  it('restarts only a listener matching a recorded launcher instance and PID', async () => {
    const incompatible = { kind: 'incompatible', status, reason: 'restart required' };
    const killProcess = vi.fn();
    const removeOwner = vi.fn();
    const readOwner = async () => ({ pid: 123, instanceId: status.instanceId });
    const verifyListener = vi.fn().mockReturnValue(true);
    const probe = vi.fn().mockResolvedValueOnce(incompatible).mockResolvedValueOnce(vacant);
    expect(await restartOwnedKermit(incompatible, { probe, readOwner, killProcess,
      verifyListener, removeOwner, sleep: async () => {} })).toEqual({ kind: 'stopped' });
    expect(killProcess).toHaveBeenCalledOnce();
    expect(killProcess).toHaveBeenCalledWith(123);
    expect(verifyListener).toHaveBeenCalledWith(123);
    expect(removeOwner).toHaveBeenCalledOnce();
    const unknownKill = vi.fn();
    expect((await restartOwnedKermit(incompatible, { readOwner: async () => null,
      killProcess: unknownKill })).kind).toBe('unverified');
    expect(unknownKill).not.toHaveBeenCalled();
    const changedKill = vi.fn();
    expect((await restartOwnedKermit(incompatible, { readOwner, probe: async () => incompatible,
      verifyListener: () => false, killProcess: changedKill })).kind).toBe('changed');
    expect(changedKill).not.toHaveBeenCalled();
  });

  it('starts a replacement only after a verified owned listener releases the port', async () => {
    const incompatible = { kind: 'incompatible', status, reason: 'restart required' };
    const probe = vi.fn().mockResolvedValueOnce(incompatible).mockResolvedValueOnce(vacant)
      .mockResolvedValueOnce(healthy);
    const launch = vi.fn().mockResolvedValue({ pid: 123, exitCode: null });
    const restartOwned = vi.fn().mockResolvedValue({ kind: 'stopped' });
    const saveOwnership = vi.fn().mockResolvedValue(true);
    expect(await ensureKermit({ ...testClock(), probe, launch, restartOwned, saveOwnership }))
      .toEqual({ kind: 'restarted', status, ownershipRecorded: true });
  });

  it('does not launch when port 8767 answers with another contract', async () => {
    const launch = vi.fn();
    const result = await ensureKermit({ probe: async () => ({ kind: 'occupied', reason: 'wrong service' }), launch });
    expect(result).toEqual({ kind: 'conflict', reason: 'wrong service' });
    expect(launch).not.toHaveBeenCalled();
  });

  it('reports reuse if a concurrent launcher won the port race', async () => {
    const probe = vi.fn().mockResolvedValueOnce(vacant).mockResolvedValueOnce(healthy);
    const result = await ensureKermit({ ...testClock(), probe,
      launch: async () => ({ pid: 123, exitCode: 1 }) });
    expect(result).toEqual({ kind: 'reused', status });
  });

  it('checks the actual HTTP path, Host, Origin, CORS, and response contract', async () => {
    const seen = [];
    let valid = true;
    const server = http.createServer((request, response) => {
      seen.push({ method: request.method, path: request.url, host: request.headers.host,
        origin: request.headers.origin });
      response.setHeader('Access-Control-Allow-Origin', valid ? 'http://127.0.0.1:5173' : 'http://other.test');
      if (request.method === 'OPTIONS') {
        response.setHeader('Access-Control-Allow-Methods', 'POST');
        response.writeHead(204);
        response.end();
        return;
      }
      response.setHeader('Content-Type', 'application/json');
      response.end(JSON.stringify(status));
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    const port = server.address().port;
    try {
      expect(await probeKermit(port)).toEqual(healthy);
      expect(seen).toEqual([
        { method: 'GET', path: '/api/kermit/v1/status', host: `127.0.0.1:${port}`,
          origin: 'http://127.0.0.1:5173' },
        { method: 'OPTIONS', path: '/api/kermit/v1/chat', host: `127.0.0.1:${port}`,
          origin: 'http://127.0.0.1:5173' },
      ]);
      valid = false;
      expect((await probeKermit(port)).kind).toBe('occupied');
      valid = true;
      const oldStatus = { ...status };
      delete oldStatus.serviceBuild;
      server.removeAllListeners('request');
      server.on('request', (_request, response) => {
        response.setHeader('Access-Control-Allow-Origin', 'http://127.0.0.1:5173');
        response.setHeader('Content-Type', 'application/json');
        response.end(JSON.stringify(oldStatus));
      });
      expect((await probeKermit(port)).kind).toBe('incompatible');
    } finally {
      await new Promise(resolve => server.close(resolve));
    }
  });

  it('isolates launch failure, early process exit, and readiness timeout', async () => {
    const clock = testClock();
    expect((await ensureKermit({ probe: async () => vacant,
      launch: async () => { throw new Error('Python missing'); } })).kind).toBe('failed');
    const probe = vi.fn().mockResolvedValue(vacant);
    const result = await ensureKermit({ ...clock, probe, launch: async () => ({ pid: 123, exitCode: 1 }) });
    expect(result.reason).toContain('code 1');
    const timeout = await ensureKermit({ ...testClock(), timeoutMs: 800, probe,
      launch: async () => ({ pid: 123, exitCode: null }) });
    expect(timeout.kind).toBe('failed');
  });

  it('launches only the fixed service command, hidden and detached, without cleanup', async () => {
    const child = new EventEmitter();
    child.pid = 123;
    child.unref = vi.fn();
    child.kill = vi.fn();
    const spawnProcess = vi.fn(() => {
      queueMicrotask(() => child.emit('spawn'));
      return child;
    });
    expect(await launchKermit({ findPython: () => 'python', spawnProcess })).toBe(child);
    const [command, args, options] = spawnProcess.mock.calls[0];
    expect(command).toBe('python');
    expect(args).toEqual(['-B', '-m', 'kermit_service']);
    expect(options).toMatchObject({ windowsHide: true, detached: true, stdio: 'ignore' });
    expect(options.env).toMatchObject({ KERMIT_SERVICE_HOST: '127.0.0.1',
      KERMIT_SERVICE_PORT: '8767', PYTHONDONTWRITEBYTECODE: '1' });
    expect(child.unref).toHaveBeenCalledTimes(1);
    expect(child.kill).not.toHaveBeenCalled();
  });
});
