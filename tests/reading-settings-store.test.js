import { beforeEach, describe, expect, it, vi } from "vitest";

const ACTIVE_STORAGE_KEY = "readingActiveMap.v1";
const SETTINGS_UPDATED_AT_STORAGE_KEY = "readingSettingsUpdatedAt.v1";

function jsonResponse(data) {
  return {
    ok: true,
    json: async () => data,
  };
}

async function flushHydration() {
  await Promise.resolve();
  await new Promise((resolve) => setTimeout(resolve, 0));
}

describe("reading settings persistence", () => {
  beforeEach(() => {
    vi.resetModules();
    vi.unstubAllGlobals();
    localStorage.clear();
    window.location.href = "http://localhost:3000/";
  });

  it("preserves every active book while hydrating settings", async () => {
    const activeMap = {
      "remote:saintfrancis": true,
      "remote:dante": true,
      "remote:mit_normalnosci": true,
      "remote:completed": false,
    };
    localStorage.setItem(ACTIVE_STORAGE_KEY, JSON.stringify(activeMap));
    const fetchSpy = vi.fn(async () => jsonResponse({}));
    vi.stubGlobal("fetch", fetchSpy);
    window.fetch = fetchSpy;

    const { readReadingActiveMap } = await import("../js/reading-settings-store.js");
    await Promise.resolve();

    expect(readReadingActiveMap()).toEqual(activeMap);
    expect(JSON.parse(localStorage.getItem(ACTIVE_STORAGE_KEY))).toEqual(activeMap);
  });

  it("keeps local active choices when the server returns an older untimestamped snapshot", async () => {
    const localActiveMap = {
      "remote:dante": false,
      "remote:duchologia": false,
      "remote:mit_normalnosci": true,
    };
    const staleServerActiveMap = {
      "remote:dante": true,
      "remote:duchologia": true,
      "remote:mit_normalnosci": true,
    };
    localStorage.setItem(ACTIVE_STORAGE_KEY, JSON.stringify(localActiveMap));

    const savedPayloads = [];
    window.location.href = "http://127.0.0.1:5173/reading.html";
    const fetchSpy = vi.fn(async (url, options = {}) => {
      if (!options.method || options.method === "GET") {
        return jsonResponse({
          activeMap: staleServerActiveMap,
          ownershipMap: {},
          selectedBook: null,
          remotePages: {},
        });
      }
      savedPayloads.push(JSON.parse(options.body));
      return jsonResponse(savedPayloads.at(-1));
    });
    vi.stubGlobal("fetch", fetchSpy);
    window.fetch = fetchSpy;

    const { readReadingActiveMap } = await import("../js/reading-settings-store.js");
    await flushHydration();

    expect(readReadingActiveMap()).toEqual(localActiveMap);
    expect(JSON.parse(localStorage.getItem(ACTIVE_STORAGE_KEY))).toEqual(localActiveMap);
    expect(JSON.parse(localStorage.getItem(SETTINGS_UPDATED_AT_STORAGE_KEY))).toBe(0);
    expect(savedPayloads.at(-1).activeMap).toEqual(localActiveMap);
  });

  it("refreshes cached settings after another tab changes the active map", async () => {
    const initialActiveMap = { "remote:wool": false };
    const nextActiveMap = {
      "remote:wool": true,
      "remote:how_to_keep_house": true,
    };
    localStorage.setItem(ACTIVE_STORAGE_KEY, JSON.stringify(initialActiveMap));
    localStorage.setItem(SETTINGS_UPDATED_AT_STORAGE_KEY, JSON.stringify(100));

    const fetchSpy = vi.fn(async () => jsonResponse({
      activeMap: initialActiveMap,
      updatedAt: 100,
    }));
    vi.stubGlobal("fetch", fetchSpy);
    window.fetch = fetchSpy;

    const { readReadingActiveMap } = await import("../js/reading-settings-store.js");
    await flushHydration();
    expect(readReadingActiveMap()).toEqual(initialActiveMap);

    localStorage.setItem(ACTIVE_STORAGE_KEY, JSON.stringify(nextActiveMap));
    localStorage.setItem(SETTINGS_UPDATED_AT_STORAGE_KEY, JSON.stringify(200));

    expect(readReadingActiveMap()).toEqual(nextActiveMap);
  });
});
