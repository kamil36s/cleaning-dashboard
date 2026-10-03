export function fullscreenElement(documentRef = document) {
  return documentRef.fullscreenElement || documentRef.webkitFullscreenElement || null;
}

export function fullscreenSupported(documentRef = document) {
  const target = documentRef.documentElement;
  return Boolean(target?.requestFullscreen || target?.webkitRequestFullscreen);
}

export async function toggleFullscreen(documentRef = document) {
  if (fullscreenElement(documentRef)) {
    const exit = documentRef.exitFullscreen || documentRef.webkitExitFullscreen;
    if (exit) await exit.call(documentRef);
    return false;
  }
  const target = documentRef.documentElement;
  const enter = target?.requestFullscreen || target?.webkitRequestFullscreen;
  if (!enter) return false;
  await enter.call(target);
  return true;
}

export function syncFullscreenUi(button, page, documentRef = document) {
  const active = Boolean(fullscreenElement(documentRef));
  button?.classList.toggle("is-active", active);
  button?.setAttribute("aria-pressed", String(active));
  if (button) {
    button.title = active ? "Wyjdź z pełnego ekranu" : "Włącz pełny ekran";
    button.setAttribute("aria-label", button.title);
  }
  const label = button?.querySelector(".synchrobook-fullscreen-label");
  const icon = button?.querySelector(".synchrobook-fullscreen-icon");
  if (label) label.textContent = active ? "Wyjdź" : "Pełny ekran";
  if (icon) icon.textContent = active ? "↙" : "⛶";
  page?.classList.toggle("is-fullscreen", active);
  return active;
}

export function syncFullscreenSidebarUi(button, page, fullscreenActive, { defaultHidden = false } = {}) {
  if (!fullscreenActive) page?.classList.remove("is-sidebar-hidden");
  else if (defaultHidden) page?.classList.add("is-sidebar-hidden");
  const hidden = Boolean(fullscreenActive && page?.classList.contains("is-sidebar-hidden"));
  if (button) {
    button.hidden = !fullscreenActive;
    button.classList.toggle("is-active", hidden);
    button.setAttribute("aria-pressed", String(hidden));
    button.setAttribute("aria-label", hidden ? "Pokaż panel książki" : "Ukryj panel książki");
    const label = button.querySelector("span:last-child");
    if (label) label.textContent = hidden ? "Pokaż panel" : "Ukryj panel";
  }
  return hidden;
}

export function toggleFullscreenSidebar(button, page) {
  page?.classList.toggle("is-sidebar-hidden");
  return syncFullscreenSidebarUi(button, page, true);
}

export function createFullscreenIdleController({
  page,
  documentRef = document,
  delay = 15000,
  onVisibilityChange = () => {},
  timers = globalThis,
}) {
  let active = false;
  let timer = null;
  const events = ["pointermove", "pointerdown", "keydown", "wheel", "touchstart"];

  const clearTimer = () => {
    if (timer != null) timers.clearTimeout(timer);
    timer = null;
  };
  const schedule = () => {
    clearTimer();
    if (active) timer = timers.setTimeout(hide, delay);
  };
  const show = () => {
    const changed = page?.classList.contains("is-controls-hidden");
    page?.classList.remove("is-controls-hidden");
    if (changed) onVisibilityChange(false);
    schedule();
  };
  const hide = () => {
    timer = null;
    if (!active) return;
    if (documentRef.querySelector?.("dialog[open]")) {
      schedule();
      return;
    }
    const changed = !page?.classList.contains("is-controls-hidden");
    page?.classList.add("is-controls-hidden");
    if (changed) onVisibilityChange(true);
  };
  const setFullscreen = (value) => {
    active = Boolean(value);
    if (active) show();
    else {
      clearTimer();
      const changed = page?.classList.contains("is-controls-hidden");
      page?.classList.remove("is-controls-hidden");
      if (changed) onVisibilityChange(false);
    }
  };
  const destroy = () => {
    setFullscreen(false);
    for (const event of events) documentRef.removeEventListener(event, show);
  };

  for (const event of events) documentRef.addEventListener(event, show, { passive: true });
  return { activity: show, destroy, hideNow: hide, setFullscreen };
}
