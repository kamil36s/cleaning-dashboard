export async function toggleElementFullscreen(documentRef, element) {
  if (!documentRef || !element) throw new Error("Widok HUD nie jest dostępny.");
  if (documentRef.fullscreenElement === element) {
    if (typeof documentRef.exitFullscreen !== "function") throw new Error("Przeglądarka nie obsługuje wyjścia z pełnego ekranu.");
    await documentRef.exitFullscreen();
    return false;
  }
  if (typeof element.requestFullscreen !== "function") throw new Error("Przeglądarka nie obsługuje pełnego ekranu.");
  await element.requestFullscreen({ navigationUI: "hide" });
  return true;
}

export function isWorkoutSessionActive(status) {
  return status === "running" || status === "paused";
}

export function pinWorkoutHudOpen(status, element, body = globalThis.document?.body) {
  if (!isWorkoutSessionActive(status) || !element) return false;
  element.hidden = false;
  body?.classList?.add("live-workout-focus-open");
  return true;
}

export async function enterElementFullscreen(documentRef, element) {
  if (!documentRef || !element) throw new Error("Widok HUD nie jest dostępny.");
  if (documentRef.fullscreenElement === element) return true;
  if (typeof element.requestFullscreen !== "function") throw new Error("Przeglądarka nie obsługuje pełnego ekranu.");
  await element.requestFullscreen({ navigationUI: "hide" });
  return true;
}

export function createExclusiveActionGate(onBusyChange = () => {}) {
  let pending = null;
  return {
    get busy() {
      return Boolean(pending);
    },
    run(action) {
      if (pending) return pending;
      onBusyChange(true);
      pending = Promise.resolve()
        .then(action)
        .finally(() => {
          pending = null;
          onBusyChange(false);
        });
      return pending;
    },
  };
}
