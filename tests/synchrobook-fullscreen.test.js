import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createFullscreenIdleController, fullscreenSupported, syncFullscreenSidebarUi, syncFullscreenUi, toggleFullscreen, toggleFullscreenSidebar } from "../js/synchrobook/fullscreen.js";

describe("Synchrobook fullscreen mode", () => {
  beforeEach(() => {
    document.body.innerHTML = `<button id="toggle"><span class="synchrobook-fullscreen-icon"></span><span class="synchrobook-fullscreen-label"></span></button>`;
    Object.defineProperty(document, "fullscreenElement", { configurable: true, value: null });
  });

  afterEach(() => vi.useRealTimers());

  it("enters fullscreen on the document element", async () => {
    document.documentElement.requestFullscreen = vi.fn().mockResolvedValue(undefined);
    expect(fullscreenSupported()).toBe(true);
    await expect(toggleFullscreen()).resolves.toBe(true);
    expect(document.documentElement.requestFullscreen).toHaveBeenCalledOnce();
  });

  it("exits fullscreen and reflects the active state in the UI", async () => {
    Object.defineProperty(document, "fullscreenElement", { configurable: true, value: document.documentElement });
    document.exitFullscreen = vi.fn().mockResolvedValue(undefined);
    const button = document.querySelector("#toggle");
    expect(syncFullscreenUi(button, document.body)).toBe(true);
    expect(button.classList.contains("is-active")).toBe(true);
    expect(button.getAttribute("aria-pressed")).toBe("true");
    expect(document.body.classList.contains("is-fullscreen")).toBe(true);
    await expect(toggleFullscreen()).resolves.toBe(false);
    expect(document.exitFullscreen).toHaveBeenCalledOnce();
  });

  it("hides and restores the book sidebar only while fullscreen is active", () => {
    const button = document.createElement("button");
    button.innerHTML = "<span></span><span></span>";
    expect(toggleFullscreenSidebar(button, document.body)).toBe(true);
    expect(document.body.classList.contains("is-sidebar-hidden")).toBe(true);
    expect(button.getAttribute("aria-label")).toBe("Pokaż panel książki");
    expect(syncFullscreenSidebarUi(button, document.body, false)).toBe(false);
    expect(document.body.classList.contains("is-sidebar-hidden")).toBe(false);
    expect(button.hidden).toBe(true);
  });

  it("starts fullscreen with the sidebar hidden without re-hiding it on later syncs", () => {
    const button = document.createElement("button");
    button.innerHTML = "<span></span><span></span>";

    expect(syncFullscreenSidebarUi(button, document.body, true, { defaultHidden: true })).toBe(true);
    expect(document.body.classList.contains("is-sidebar-hidden")).toBe(true);
    expect(toggleFullscreenSidebar(button, document.body)).toBe(false);
    expect(syncFullscreenSidebarUi(button, document.body, true)).toBe(false);
    expect(document.body.classList.contains("is-sidebar-hidden")).toBe(false);
  });

  it("hides all fullscreen chrome after 15 seconds and restores it on movement", () => {
    vi.useFakeTimers();
    const onVisibilityChange = vi.fn();
    const controller = createFullscreenIdleController({
      page: document.body, delay: 15000, onVisibilityChange,
    });
    controller.setFullscreen(true);

    vi.advanceTimersByTime(14999);
    expect(document.body.classList.contains("is-controls-hidden")).toBe(false);
    vi.advanceTimersByTime(1);
    expect(document.body.classList.contains("is-controls-hidden")).toBe(true);

    document.dispatchEvent(new Event("pointermove"));
    expect(document.body.classList.contains("is-controls-hidden")).toBe(false);
    expect(onVisibilityChange).toHaveBeenLastCalledWith(false);

    controller.setFullscreen(false);
    vi.advanceTimersByTime(15000);
    expect(document.body.classList.contains("is-controls-hidden")).toBe(false);
    controller.destroy();
  });
});
