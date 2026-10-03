import { afterEach, describe, expect, it, vi } from "vitest";

import {
  initJournalApp,
  journalDraftStorageKey,
  journalLocalDateTime,
  splitJournalTags,
} from "../js/journal.js";

function markup() {
  document.body.innerHTML = `
    <div id="journal-app">
      <button id="journal-new-entry"></button>
      <button id="journal-new-poem"></button>
      <strong id="journal-stat-count"></strong><strong id="journal-stat-poems"></strong><strong id="journal-stat-voice"></strong><strong id="journal-stat-latest"></strong>
      <aside id="journal-composer-panel">
        <div id="journal-composer-shell">
          <span id="journal-form-kicker"></span><h2 id="journal-form-title"></h2>
          <div id="journal-edit-audio" hidden><audio id="journal-edit-audio-player"></audio><small id="journal-edit-audio-meta"></small></div>
          <form id="journal-form">
          <select name="entryKind"><option value="journal">Wpis</option><option value="poem">Wiersz</option></select>
          <input name="title"><input name="entryDate" type="date"><input name="entryTime" type="time"><input name="tags"><input name="location">
          <div id="journal-editor-toolbar"><button id="journal-editor-source-toggle" type="button"></button></div>
          <select id="journal-editor-block"><option value="p">Akapit</option></select>
          <div id="journal-rich-editor" contenteditable="true"></div>
          <textarea name="content" hidden></textarea>
          <input name="illustrationFile" type="file"><input name="illustrationAlt">
          <div id="journal-illustration-preview" hidden><img id="journal-illustration-image"></div>
          <button id="journal-remove-illustration" type="button"></button>
          <button id="journal-save-entry" type="submit"></button>
          <button id="journal-cancel-edit" type="button"></button>
          <small id="journal-draft-status"></small>
          </form>
          <div id="journal-form-status"></div>
        </div>
      </aside>
      <input id="journal-search"><input id="journal-show-poems" type="checkbox"><input id="journal-show-context" type="checkbox">
      <select id="journal-year-filter"><option value="">Wszystkie</option></select>
      <select id="journal-month-filter"><option value="">Wszystkie</option></select>
      <button id="journal-filter-reset" type="button"></button>
      <div id="journal-list-status"></div><div id="journal-composer-slot"></div>
      <div id="journal-entry-list"></div>
      <div id="journal-empty"><strong></strong><p></p></div>
    </div>`;
  const root = document.getElementById("journal-app");
  root.querySelector("#journal-composer-panel").scrollIntoView = vi.fn();
  return root;
}

describe("journal app", () => {
  afterEach(() => {
    localStorage.clear();
    document.body.replaceChildren();
    vi.restoreAllMocks();
  });

  it("normalizes local dates and unique tags", () => {
    expect(journalLocalDateTime(new Date("2026-07-21T12:30:00Z"))).toHaveLength(16);
    expect(splitJournalTags("sen, praca, sen")).toEqual(["sen", "praca"]);
  });

  it("renders manual and published entries and supports create plus edit", async () => {
    const root = markup();
    let entries = [{
      id: "voice-1", title: "Sen", content: "Uporządkowany tekst", entryDate: "2026-07-21T08:00:00Z",
      tags: ["sen"], sourceType: "voice-journal", sourceVoiceJournalEntryId: "a".repeat(32),
      sourceMetadata: {
        originalFilename: "sen.aac", model: "turbo",
        audioUrl: `/api/voice-journal/entries/${"a".repeat(32)}/audio`,
      },
    }, {
      id: "poem-1", title: "Ararat", content: "<p>Wers pierwszy</p>", contentFormat: "html",
      entryDate: "2023-07-19", entryKind: "poem", tags: ["poem"], sourceType: "tumblr",
      sourceMetadata: { tumblr: { publishedLocal: "2023-07-19T15:03:03", url: "https://example.test/post" } },
    }];
    const fetchEntries = vi.fn(async () => entries);
    const createEntry = vi.fn(async (payload) => {
      entries = [{ id: "manual-1", sourceType: "manual", sourceMetadata: {}, ...payload }, ...entries];
      return entries[0];
    });
    const updateEntry = vi.fn(async (id, patch) => {
      entries = entries.map((entry) => entry.id === id ? { ...entry, ...patch } : entry);
      return entries.find((entry) => entry.id === id);
    });
    const fetchContexts = vi.fn(async () => ({
      "2026-07-21": {
        timelineGroups: [{ id: "relationships", label: "Relationships", color: "#c86b7b", items: [{ title: "Weronika", type: "period" }] }],
        activityGroups: [{ id: "lastfm", label: "Last.fm", color: "#d92323", events: [{ title: "30 scrobbles", summary: "Artist: Jute Gyte" }] }],
      },
    }));
    await initJournalApp(root, { fetchEntries, fetchContexts, createEntry, updateEntry, deleteEntry: vi.fn() });

    expect(root.querySelector("#journal-stat-count").textContent).toBe("1");
    expect(root.querySelector("#journal-stat-poems").textContent).toBe("1");
    expect(root.querySelectorAll(".journal-entry-card")).toHaveLength(1);
    expect(root.querySelector("#journal-year-filter").value).toBe(String(new Date().getFullYear()));
    expect(root.querySelector("#journal-composer-panel > #journal-composer-shell")).not.toBeNull();
    root.querySelector("#journal-new-poem").click();
    expect(root.querySelector("#journal-form").elements.entryKind.value).toBe("poem");
    expect(root.querySelector("#journal-composer-slot > #journal-composer-shell")).not.toBeNull();
    root.querySelector("#journal-new-entry").click();
    expect(root.querySelector("#journal-form").elements.entryKind.value).toBe("journal");
    expect(root.querySelector("#journal-composer-slot > #journal-composer-shell")).not.toBeNull();
    expect(root.querySelector("#journal-cancel-edit").hidden).toBe(false);
    expect(root.querySelector("#journal-cancel-edit").textContent).toBe("Anuluj");
    expect(root.querySelector(".journal-entry-source").textContent).toContain("głosowego");
    expect(root.querySelector(".journal-source-details").textContent).toContain("Metadane");
    expect(root.querySelectorAll('.journal-entry-card[data-entry-id="voice-1"] .journal-entry-actions')).toHaveLength(2);

    root.querySelector('.journal-entry-card[data-entry-id="voice-1"] .journal-entry-actions.is-top button').click();
    expect(root.querySelector("#journal-composer-slot > #journal-composer-shell")).not.toBeNull();
    expect(root.querySelector("#journal-edit-audio").hidden).toBe(false);
    expect(root.querySelector("#journal-edit-audio-player").getAttribute("src"))
      .toBe(`/api/voice-journal/entries/${"a".repeat(32)}/audio`);
    root.querySelector("#journal-cancel-edit").click();
    expect(root.querySelector("#journal-composer-panel > #journal-composer-shell")).not.toBeNull();
    expect(root.querySelector("#journal-edit-audio").hidden).toBe(true);

    root.querySelector("#journal-show-poems").click();
    expect(root.querySelectorAll(".journal-entry-card")).toHaveLength(1);
    root.querySelector("#journal-year-filter").value = "";
    root.querySelector("#journal-year-filter").dispatchEvent(new Event("change", { bubbles: true }));
    expect(root.querySelectorAll(".journal-entry-card")).toHaveLength(2);
    expect(root.querySelector('.journal-entry-card[data-entry-id="poem-1"]').classList.contains("is-poem")).toBe(true);
    root.querySelector("#journal-show-poems").click();
    root.querySelector("#journal-show-context").click();
    await vi.waitFor(() => expect(fetchContexts).toHaveBeenCalledOnce());
    expect(fetchContexts).toHaveBeenCalledWith(["2023-07-19", "2026-07-21"]);
    await vi.waitFor(() => expect(root.querySelector(".journal-entry-context").textContent).toContain("Weronika"));
    expect(root.querySelector(".journal-entry-context").textContent).toContain("30 scrobbles");

    const form = root.querySelector("#journal-form");
    form.elements.title.value = "Nowy dzień";
    root.querySelector("#journal-rich-editor").innerHTML = "<p>Treść <strong>ręczna</strong></p>";
    form.elements.tags.value = "dom, myśli";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(createEntry).toHaveBeenCalledOnce());
    expect(createEntry).toHaveBeenCalledWith(expect.objectContaining({
      entryKind: "journal",
      content: "<p>Treść <strong>ręczna</strong></p>",
      contentFormat: "html",
    }));
    await vi.waitFor(() => expect(root.querySelectorAll(".journal-entry-card")).toHaveLength(2));

    root.querySelector('.journal-entry-card[data-entry-id="manual-1"] .journal-text-button').click();
    root.querySelector("#journal-rich-editor").innerHTML = "<p><em>Treść poprawiona</em></p>";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(updateEntry).toHaveBeenCalledWith("manual-1", expect.objectContaining({
      content: "<p><em>Treść poprawiona</em></p>",
      contentFormat: "html",
    })));
  });

  it("restores a new-entry autosave after editing and saving another post", async () => {
    const root = markup();
    let entries = [{
      id: "manual-existing",
      title: "Starszy wpis",
      content: "<p>Starsza treść</p>",
      contentFormat: "html",
      entryDate: "2026-08-14T08:00:00Z",
      tags: [],
      sourceType: "manual",
    }];
    const updateEntry = vi.fn(async (id, patch) => {
      entries = entries.map((entry) => entry.id === id ? { ...entry, ...patch } : entry);
      return entries[0];
    });
    await initJournalApp(root, {
      fetchEntries: vi.fn(async () => entries),
      createEntry: vi.fn(),
      updateEntry,
      deleteEntry: vi.fn(),
    });

    const form = root.querySelector("#journal-form");
    form.elements.title.value = "Tekst, którego nie wolno zgubić";
    const editor = root.querySelector("#journal-rich-editor");
    editor.innerHTML = "<p>Długa, niezapisana treść nowego wpisu.</p>";
    editor.dispatchEvent(new Event("input", { bubbles: true }));

    root.querySelector('.journal-entry-card[data-entry-id="manual-existing"] .journal-text-button').click();
    expect(JSON.parse(localStorage.getItem(journalDraftStorageKey())).content)
      .toBe("<p>Długa, niezapisana treść nowego wpisu.</p>");

    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(updateEntry).toHaveBeenCalledOnce());
    await vi.waitFor(() => {
      expect(form.elements.title.value).toBe("Tekst, którego nie wolno zgubić");
      expect(editor.innerHTML).toBe("<p>Długa, niezapisana treść nowego wpisu.</p>");
    });
    expect(root.querySelector("#journal-draft-status").textContent).toContain("Przywrócono autoszkic");
  });

  it("keeps the draft base version and content after a remote conflict", async () => {
    const root = markup();
    const entry = {
      id: "versioned-entry", version: 3, title: "Remote", content: "remote text",
      entryDate: new Date().toISOString(), tags: [], sourceType: "manual",
    };
    localStorage.setItem(journalDraftStorageKey(entry.id), JSON.stringify({
      version: 1, baseVersion: 1, title: "Local draft", content: "unsaved text",
      contentFormat: "text", savedAt: new Date().toISOString(),
    }));
    const updateEntry = vi.fn().mockRejectedValue(Object.assign(new Error("Conflict"), { code: "VERSION_CONFLICT" }));
    await initJournalApp(root, { fetchEntries: async () => [entry], updateEntry });
    root.querySelector('.journal-entry-card .journal-text-button').click();
    root.querySelector('#journal-form').dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(updateEntry).toHaveBeenCalledWith(entry.id, expect.objectContaining({ expectedVersion: 1 })));
    await vi.waitFor(() => expect(root.querySelector('#journal-form-status').textContent).toBe("Conflict"));
    const draft = JSON.parse(localStorage.getItem(journalDraftStorageKey(entry.id)));
    expect(draft.baseVersion).toBe(1);
    expect(draft.content).toContain("unsaved text");
  });

  it("restores an autosaved draft after the page is reopened", async () => {
    let root = markup();
    const dependencies = {
      fetchEntries: vi.fn(async () => []),
      createEntry: vi.fn(),
      updateEntry: vi.fn(),
      deleteEntry: vi.fn(),
    };
    await initJournalApp(root, dependencies);
    root.querySelector("#journal-form").elements.title.value = "Szkic po odświeżeniu";
    root.querySelector("#journal-rich-editor").innerHTML = "<p>Ta treść ma wrócić.</p>";
    root.querySelector("#journal-rich-editor").dispatchEvent(new Event("input", { bubbles: true }));
    await vi.waitFor(() => expect(localStorage.getItem(journalDraftStorageKey())).not.toBeNull());

    root = markup();
    await initJournalApp(root, dependencies);

    expect(root.querySelector("#journal-form").elements.title.value).toBe("Szkic po odświeżeniu");
    expect(root.querySelector("#journal-rich-editor").innerHTML).toBe("<p>Ta treść ma wrócić.</p>");
    expect(root.querySelector("#journal-draft-status").textContent).toContain("Przywrócono autoszkic");
  });
});
