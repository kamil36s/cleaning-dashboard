// Keep in sync with kermit_service/contract.py when the browser API changes.
export const KERMIT_SERVICE_BUILD = 'unified-chat-v1';
export const KERMIT_CHAT_CAPABILITY = 'chat@1';

export function isCompatibleKermitStatus(body) {
  return body?.contractVersion === 1 && body.status === 'ok' &&
    body.serviceAvailable === true && body.serviceBuild === KERMIT_SERVICE_BUILD &&
    Array.isArray(body.capabilities) && body.capabilities.includes(KERMIT_CHAT_CAPABILITY);
}
