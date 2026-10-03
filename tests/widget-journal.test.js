import { afterEach, describe, expect, it, vi } from "vitest";

import { initJournalWidget } from "../js/widget-journal.js";

describe("journal dashboard widget", () => {
  afterEach(() => {
    document.body.replaceChildren();
    vi.restoreAllMocks();
  });

  it("shows stats and saves a quick manual note", async () => {
    document.body.innerHTML = '<section class="card journal-widget"><div id="journal-widget-root"></div></section>';
    const root = document.getElementById("journal-widget-root");
    let entries = [{
      id: "voice-1", title: "Sen", content: "Opis", entryDate: "2026-07-21T08:00:00Z", sourceType: "voice-journal",
    }, {
      id: "poem-1", title: "Ararat", content: "Wiersz", entryDate: "2023-07-19", entryKind: "poem", sourceType: "tumblr",
    }];
    const fetchEntries = vi.fn(async () => entries);
    const createEntry = vi.fn(async (payload) => {
      entries = [{ id: "manual-1", sourceType: "manual", ...payload }, ...entries];
    });
    await initJournalWidget(root, { fetchEntries, createEntry });

    expect(root.querySelector("#journal-widget-count").textContent).toBe("1");
    expect(root.querySelector("#journal-widget-voice").textContent).toBe("1");
    expect(root.querySelector("#journal-widget-recent").textContent).not.toContain("Ararat");
    const form = root.querySelector("form");
    form.elements.title.value = "Szybka myśl";
    form.elements.content.value = "Nie zapomnieć o tym.";
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    await vi.waitFor(() => expect(createEntry).toHaveBeenCalledWith(expect.objectContaining({
      title: "Szybka myśl",
      content: "Nie zapomnieć o tym.",
      tags: [],
    })));
    await vi.waitFor(() => expect(root.querySelector("#journal-widget-count").textContent).toBe("2"));
  });
});
