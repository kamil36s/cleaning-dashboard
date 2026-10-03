export function onDomReady(callback) {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", callback, { once: true });
    return;
  }
  queueMicrotask(() => callback(new Event("DOMContentLoaded")));
}
