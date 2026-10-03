import { afterEach, describe, expect, it, vi } from "vitest";

describe("Journal HTR dashboard widget", () => {
  afterEach(() => {
    document.body.innerHTML = "";
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  it("renders compact metrics and the backend-provided deep link", async () => {
    document.body.innerHTML = `
      <section id="journal-htr-card">
        <span id="journal-htr-widget-service"></span>
        <a id="journal-htr-widget-action"></a>
        <div id="journal-htr-widget-root"></div>
      </section>
    `;
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({
        enabled: true,
        services: { escriptorium: { online: true } },
        stats: {
          totalPages: 8,
          pendingSegmentation: 2,
          pendingTranscription: 1,
          unreviewedLines: 126,
          approvedTrainingLines: 240,
          activeModelVersion: "v2",
          lastCer: 0.083,
        },
        nextStep: {
          title: "Sprawdź 126 rozpoznanych linii",
          reason: "Predykcje wymagają korekty.",
          actionLabel: "Otwórz korektę",
          actionUrl: "./journal-ocr.html#correction",
        },
      }),
    })));

    await import("../js/widget-journal-htr.js");
    await vi.waitFor(() =>
      expect(document.querySelector("#journal-htr-widget-root").textContent).toContain("126")
    );
    expect(document.querySelector("#journal-htr-widget-service").textContent).toBe("HTR online");
    expect(document.querySelector("#journal-htr-widget-action").getAttribute("href")).toContain("#correction");
    expect(document.querySelector("#journal-htr-widget-root").textContent).toContain("v2");
  });

  it("shows an honest backend-offline state", async () => {
    document.body.innerHTML = `
      <span id="journal-htr-widget-service"></span>
      <a id="journal-htr-widget-action"></a>
      <div id="journal-htr-widget-root"></div>
    `;
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: false,
      status: 503,
      statusText: "Unavailable",
      json: async () => ({ error: "Backend offline" }),
    })));

    await import("../js/widget-journal-htr.js");
    await vi.waitFor(() =>
      expect(document.querySelector("#journal-htr-widget-service").textContent).toBe("Backend offline")
    );
    expect(document.querySelector("#journal-htr-widget-root").textContent).toContain("Nie udało się");
  });

  it("starts a stopped OCR server from the widget", async () => {
    document.body.innerHTML = `
      <span id="journal-htr-widget-service"></span>
      <button id="journal-htr-widget-toggle"></button>
      <a id="journal-htr-widget-action"></a>
      <div id="journal-htr-widget-root"></div>
    `;
    const stopped = {
      enabled: true,
      runtime: { state: "stopped", canStart: true, canStop: false },
      services: { escriptorium: { online: false } },
      stats: {},
      nextStep: {},
    };
    const online = {
      ...stopped,
      runtime: { state: "online", canStart: false, canStop: true },
      services: { escriptorium: { online: true } },
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => stopped })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ runtime: { state: "starting" } }),
      })
      .mockResolvedValueOnce({ ok: true, json: async () => online });
    vi.stubGlobal("fetch", fetchMock);

    await import("../js/widget-journal-htr.js");
    await vi.waitFor(() =>
      expect(document.querySelector("#journal-htr-widget-toggle").textContent).toBe("Uruchom serwer")
    );
    document.querySelector("#journal-htr-widget-toggle").click();

    await vi.waitFor(() =>
      expect(document.querySelector("#journal-htr-widget-toggle").textContent).toBe("Wyłącz serwer")
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/journal-htr/server/start",
      expect.objectContaining({ method: "POST" }),
    );
    expect(document.querySelector("#journal-htr-widget-action").hidden).toBe(false);
  });

  it("stops an online OCR server from the widget", async () => {
    document.body.innerHTML = `
      <span id="journal-htr-widget-service"></span>
      <button id="journal-htr-widget-toggle"></button>
      <a id="journal-htr-widget-action"></a>
      <div id="journal-htr-widget-root"></div>
    `;
    const online = {
      enabled: true,
      runtime: { state: "online", canStart: false, canStop: true },
      services: { escriptorium: { online: true } },
      stats: {},
      nextStep: {},
    };
    const stopped = {
      ...online,
      runtime: { state: "stopped", canStart: true, canStop: false },
      services: { escriptorium: { online: false } },
    };
    const fetchMock = vi.fn()
      .mockResolvedValueOnce({ ok: true, json: async () => online })
      .mockResolvedValueOnce({
        ok: true,
        json: async () => ({ runtime: { state: "stopping" } }),
      })
      .mockResolvedValueOnce({ ok: true, json: async () => stopped });
    vi.stubGlobal("fetch", fetchMock);

    await import("../js/widget-journal-htr.js");
    await vi.waitFor(() =>
      expect(document.querySelector("#journal-htr-widget-toggle").textContent).toBe("Wyłącz serwer")
    );
    document.querySelector("#journal-htr-widget-toggle").click();

    await vi.waitFor(() =>
      expect(document.querySelector("#journal-htr-widget-toggle").textContent).toBe("Uruchom serwer")
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/journal-htr/server/stop",
      expect.objectContaining({ method: "POST" }),
    );
    expect(document.querySelector("#journal-htr-widget-action").hidden).toBe(true);
  });
});
