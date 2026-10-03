import { KERMIT_SERVICE_BASE } from './kermit-config.js';
import { isCompatibleKermitStatus } from './kermit-contract.js';

export class KermitClientError extends Error {
  constructor(kind, message, body = null) {
    super(message);
    this.kind = kind;
    this.body = body;
  }
}

async function request(path, options = {}) {
  let response;
  try {
    response = await fetch(`${KERMIT_SERVICE_BASE}/api/kermit/v1/${path}`, {
      cache: 'no-store', ...options,
    });
  } catch {
    throw new KermitClientError('connection', 'Cannot connect to the local Kermit service.');
  }
  let body;
  try { body = await response.json(); }
  catch { throw new KermitClientError('protocol', 'Kermit returned an unreadable response.'); }
  if (path === 'chat' && (response.status === 404 || response.status === 405)) {
    throw new KermitClientError('incompatible', 'Kermit restart required: this service lacks unified chat.', body);
  }
  if (body?.contractVersion != null && body.contractVersion !== 1) {
    throw new KermitClientError('incompatible', 'Kermit restart required: API version differs from this dashboard.', body);
  }
  if (!body || body.contractVersion !== 1) {
    throw new KermitClientError('protocol', 'Kermit returned an unreadable API response.', body);
  }
  return body;
}

export async function getKermitStatus() {
  const body = await request('status');
  if (body.status !== 'ok') throw new KermitClientError('service', 'Kermit status check failed.', body);
  if (!isCompatibleKermitStatus(body)) {
    throw new KermitClientError('incompatible', 'Kermit restart required: the running service is outdated.', body);
  }
  return body;
}

export const askKermit = (question, profile, allowMemoryPressure = false) => request('ask', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ contractVersion: 1, question, profile, ...(allowMemoryPressure ? { allowMemoryPressure: true } : {}) }),
});

export const chatKermit = (message, profile, history = [], conversationState = null, allowMemoryPressure = false) => request('chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ contractVersion: 1, message, profile, history,
    ...(conversationState ? { conversationState } : {}),
    ...(allowMemoryPressure ? { allowMemoryPressure: true } : {}) }),
});
