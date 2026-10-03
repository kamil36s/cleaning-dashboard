// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { chatKermit, getKermitStatus } from '../js/kermit-client.js';
import { KERMIT_SERVICE_BUILD, KERMIT_CHAT_CAPABILITY } from '../js/kermit-contract.js';

const reply = (body, status = 200) => ({ status, json: async () => body });
const base = { contractVersion: 1, status: 'ok', serviceAvailable: true,
  serviceBuild: KERMIT_SERVICE_BUILD, capabilities: [KERMIT_CHAT_CAPABILITY] };

describe('Kermit browser client diagnostics', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('rejects an old /status contract with a restart diagnostic', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply({ ...base, serviceBuild: undefined })));
    await expect(getKermitStatus()).rejects.toMatchObject({ kind: 'incompatible' });
  });

  it('recognizes the discovered old-service /chat 404 response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply({ status: 'not_found' }, 404)));
    await expect(chatKermit('hi', 'quick')).rejects.toMatchObject({ kind: 'incompatible' });
  });

  it('identifies an API contract version mismatch as a restart problem', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply({ contractVersion: 2, status: 'ok' })));
    await expect(getKermitStatus()).rejects.toMatchObject({ kind: 'incompatible' });
  });

  it('separates a connection failure from model/resource responses', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('Failed to fetch')));
    await expect(getKermitStatus()).rejects.toMatchObject({ kind: 'connection' });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(reply({ contractVersion: 1,
      status: 'confirmation_required', resource: { availableMb: 6000 } }, 409)));
    await expect(chatKermit('hi', 'quick')).resolves.toMatchObject({ status: 'confirmation_required' });
  });
});
