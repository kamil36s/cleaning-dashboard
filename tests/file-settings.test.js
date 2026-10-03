import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("file settings persistence", () => {
  beforeEach(() => {
    vi.resetModules();
    window.happyDOM.setURL("http://localhost:5173/cleaning-dashboard/");
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("does not use keepalive for payloads larger than the browser limit", async () => {
    const fetchMock = vi.fn(async (_url, options) => ({
      ok: true,
      json: async () => ({ ok: true, data: JSON.parse(options.body).data }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    const { saveFileSetting } = await import("../js/file-settings.js");

    await saveFileSetting("todo", [{ title: "x".repeat(70_000) }]);

    expect(fetchMock).toHaveBeenCalledOnce();
    expect(fetchMock.mock.calls[0][1].keepalive).toBe(false);
  });

  it("keeps navigation-safe persistence for small payloads", async () => {
    const fetchMock = vi.fn(async (_url, options) => ({
      ok: true,
      json: async () => ({ ok: true, data: JSON.parse(options.body).data }),
    }));
    vi.stubGlobal("fetch", fetchMock);
    const { saveFileSetting } = await import("../js/file-settings.js");

    await saveFileSetting("todo", [{ title: "small" }]);

    expect(fetchMock.mock.calls[0][1].keepalive).toBe(true);
  });
});
