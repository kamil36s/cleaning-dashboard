import { beforeEach, describe, expect, it, vi } from "vitest";
import { SynchrobookReader } from "../js/synchrobook/reader.js";
import { findActiveSentenceIndex } from "../js/synchrobook/utils.js";

describe("Synchrobook reader", () => {
  beforeEach(() => {
    document.body.innerHTML = `<div id="scroll"><article id="text"></article></div>`;
  });

  it("uses indexed binary lookup for the active sentence", () => {
    const rows = [{ start: 1 }, { start: 5 }, { start: 9 }, { start: 18 }];
    expect(findActiveSentenceIndex(rows, 0)).toBe(-1);
    expect(findActiveSentenceIndex(rows, 8)).toBe(1);
    expect(findActiveSentenceIndex(rows, 18)).toBe(3);
  });

  it("clicking an aligned sentence seeks to its timestamp", () => {
    const onSeek = vi.fn();
    const reader = new SynchrobookReader({
      scroller: document.querySelector("#scroll"), article: document.querySelector("#text"),
      onSeek, onChapter: vi.fn(),
    });
    reader.load({ chapters: [{ id: "ch01", title: "Chapter 1", paragraphs: [{
      id: "ch01-p001", heading: false, sentences: [
        { id: "ch01-p001-s001", originalText: "Aligned sentence." },
        { id: "ch01-p001-s002", originalText: "Unaligned sentence." },
      ],
    }] }] }, { chapters: [{ id: "ch01", sentences: [
      { id: "ch01-p001-s001", text: "Aligned sentence.", start: 42.5, end: 44, confidence: 0.9 },
      { id: "ch01-p001-s002", text: "Unaligned sentence.", start: null, end: null, confidence: 0 },
    ] }] });
    reader.renderChapter("ch01", { notify: false });
    document.querySelector('[data-sentence-id="ch01-p001-s001"]').click();
    expect(onSeek).toHaveBeenCalledWith(42.5, expect.objectContaining({ id: "ch01-p001-s001" }));
    document.querySelector('[data-sentence-id="ch01-p001-s002"]').click();
    expect(onSeek).toHaveBeenCalledTimes(1);
  });

  it("keeps the current sentence highlighted and recenters it after a mode change", () => {
    const reader = new SynchrobookReader({
      scroller: document.querySelector("#scroll"), article: document.querySelector("#text"),
      onSeek: vi.fn(), onChapter: vi.fn(),
    });
    reader.load({ chapters: [{ id: "ch01", title: "Chapter 1", paragraphs: [{
      id: "ch01-p001", heading: false, sentences: [{ id: "s1", originalText: "Follow me." }],
    }] }] }, { chapters: [{ id: "ch01", sentences: [{ id: "s1", text: "Follow me.", start: 5, end: 6, confidence: 1 }] }] });
    reader.renderChapter("ch01", { notify: false });
    const sentence = document.querySelector('[data-sentence-id="s1"]');
    sentence.scrollIntoView = vi.fn();
    reader.sync(5.5);
    reader.sync(5.5, { forceScroll: true });
    expect(sentence.classList.contains("is-active")).toBe(true);
    expect(sentence.scrollIntoView).toHaveBeenCalledWith({ behavior: "auto", block: "center" });
  });

  it("marks the commentary chunk range without replacing the active sentence state", () => {
    const reader = new SynchrobookReader({
      scroller: document.querySelector("#scroll"), article: document.querySelector("#text"),
      onSeek: vi.fn(), onChapter: vi.fn(),
    });
    reader.load({ chapters: [{ id: "ch01", title: "Chapter 1", paragraphs: [{
      id: "p1", heading: false, sentences: [
        { id: "s1", originalText: "One." }, { id: "s2", originalText: "Two." },
        { id: "s3", originalText: "Three." }, { id: "s4", originalText: "Four." },
      ],
    }] }] }, { chapters: [{ id: "ch01", sentences: [
      { id: "s1", start: 1, end: 2 }, { id: "s2", start: 2, end: 3 },
      { id: "s3", start: 3, end: 4 }, { id: "s4", start: 4, end: 5 },
    ] }] });
    reader.renderChapter("ch01", { notify: false });
    reader.setCommentaryRange({ start_source_id: "s1", end_source_id: "s3" });
    expect(document.querySelectorAll(".is-commentary-range")).toHaveLength(3);
    reader.sync(2.5);
    const active = document.querySelector('[data-sentence-id="s2"]');
    expect(active.classList.contains("is-commentary-range")).toBe(true);
    expect(active.classList.contains("is-active")).toBe(true);
    reader.setCommentaryRange(null);
    expect(document.querySelectorAll(".is-commentary-range")).toHaveLength(0);
    expect(active.classList.contains("is-active")).toBe(true);
  });
});
