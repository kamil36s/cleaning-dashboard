(() => {
  if (window.__fetchTrackerInstalled) return;
  window.__fetchTrackerInstalled = true;
  window.__pendingRequests = 0;

  const notify = () => {
    document.dispatchEvent(new Event("dashboard:net"));
  };

  const inc = () => {
    window.__pendingRequests += 1;
    notify();
  };

  const dec = () => {
    window.__pendingRequests = Math.max(0, window.__pendingRequests - 1);
    notify();
  };

  const originalFetch = window.fetch;
  if (typeof originalFetch === "function") {
    window.fetch = (...args) => {
      inc();
      return originalFetch(...args).finally(dec);
    };
  }

  if (window.XMLHttpRequest && window.XMLHttpRequest.prototype) {
    const originalSend = window.XMLHttpRequest.prototype.send;
    window.XMLHttpRequest.prototype.send = function (...args) {
      if (!this.__tracked) {
        this.__tracked = true;
        inc();
        this.addEventListener(
          "loadend",
          () => {
            dec();
          },
          { once: true }
        );
      }
      return originalSend.apply(this, args);
    };
  }
})();
