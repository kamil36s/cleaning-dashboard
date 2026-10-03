import { findActiveSentenceIndex } from "./utils.js";

export class SynchrobookReader {
  constructor({ scroller, article, onSeek, onChapter }) {
    this.scroller = scroller;
    this.article = article;
    this.onSeek = onSeek;
    this.onChapter = onChapter;
    this.book = null;
    this.alignment = null;
    this.alignmentById = new Map();
    this.timeline = [];
    this.chapterId = null;
    this.activeId = null;
    this.sourceOrder = new Map();
    this.commentaryRange = null;
    this.autoScroll = true;
    this.manualScrollUntil = 0;
    for (const event of ["wheel", "touchmove", "pointerdown"]) {
      scroller.addEventListener(event, () => { this.manualScrollUntil = performance.now() + 4500; }, { passive: true });
    }
    article.addEventListener("click", (event) => {
      const element = event.target.closest("[data-sentence-id]");
      if (!element) return;
      const aligned = this.alignmentById.get(element.dataset.sentenceId);
      if (aligned?.start == null) return;
      this.onSeek(Number(aligned.start), aligned);
    });
  }

  load(book, alignment) {
    this.book = book;
    this.alignment = alignment;
    this.alignmentById = new Map();
    this.timeline = [];
    this.sourceOrder = new Map();
    let sourceIndex = 0;
    for (const chapter of book.chapters || []) {
      for (const paragraph of chapter.paragraphs || []) {
        for (const sentence of paragraph.sentences || []) this.sourceOrder.set(sentence.id, sourceIndex++);
      }
    }
    for (const chapter of alignment.chapters || []) {
      for (const sentence of chapter.sentences || []) {
        this.alignmentById.set(sentence.id, { ...sentence, chapterId: chapter.id });
        if (sentence.start != null) this.timeline.push({ ...sentence, chapterId: chapter.id });
      }
    }
    this.timeline.sort((left, right) => Number(left.start) - Number(right.start));
  }

  clear() {
    this.book = null;
    this.alignment = null;
    this.alignmentById.clear();
    this.timeline = [];
    this.chapterId = null;
    this.activeId = null;
    this.sourceOrder.clear();
    this.commentaryRange = null;
    this.article.replaceChildren();
    this.article.hidden = true;
  }

  renderChapter(chapterId, { notify = true } = {}) {
    const chapter = (this.book?.chapters || []).find((row) => row.id === chapterId);
    if (!chapter) return;
    this.chapterId = chapterId;
    this.activeId = null;
    this.article.replaceChildren();
    const heading = document.createElement("h2");
    heading.textContent = chapter.title;
    this.article.append(heading);
    for (const paragraph of chapter.paragraphs || []) {
      const container = document.createElement(paragraph.heading ? "h3" : "p");
      container.className = "synchrobook-paragraph";
      for (const sentence of paragraph.sentences || []) {
        const span = document.createElement("span");
        const aligned = this.alignmentById.get(sentence.id);
        span.className = `synchrobook-sentence ${aligned?.start != null ? "is-aligned" : "is-unaligned"}`;
        span.dataset.sentenceId = sentence.id;
        span.textContent = sentence.originalText || sentence.text;
        if (aligned?.start != null) span.title = "Kliknij, aby przejść do tego zdania";
        container.append(span, document.createTextNode(" "));
      }
      this.article.append(container);
    }
    this.applyCommentaryRange();
    this.article.hidden = false;
    if (notify) this.onChapter(chapter);
  }

  setCommentaryRange(chunk) {
    this.commentaryRange = chunk ? {
      startSourceId: chunk.start_source_id,
      endSourceId: chunk.end_source_id,
    } : null;
    this.applyCommentaryRange();
  }

  applyCommentaryRange() {
    const sentences = this.article.querySelectorAll("[data-sentence-id]");
    for (const sentence of sentences) sentence.classList.remove("is-commentary-range");
    if (!this.commentaryRange) return;
    const start = this.sourceOrder.get(this.commentaryRange.startSourceId);
    const end = this.sourceOrder.get(this.commentaryRange.endSourceId);
    if (!Number.isInteger(start) || !Number.isInteger(end) || start > end) return;
    for (const sentence of sentences) {
      const position = this.sourceOrder.get(sentence.dataset.sentenceId);
      if (Number.isInteger(position) && position >= start && position <= end) sentence.classList.add("is-commentary-range");
    }
  }

  sync(currentTime, { forceScroll = false } = {}) {
    const index = findActiveSentenceIndex(this.timeline, currentTime);
    if (index < 0) {
      this.article.querySelector(".synchrobook-sentence.is-active")?.classList.remove("is-active");
      this.activeId = null;
      return null;
    }
    const active = this.timeline[index];
    const next = this.timeline[index + 1];
    if (active.end != null && currentTime > Number(active.end) + 6 && (!next || Number(next.start) > currentTime + 6)) {
      this.article.querySelector(".synchrobook-sentence.is-active")?.classList.remove("is-active");
      this.activeId = null;
      return null;
    }
    if (active.chapterId !== this.chapterId) this.renderChapter(active.chapterId, { notify: false });
    const changed = active.id !== this.activeId;
    if (changed) this.article.querySelector(".synchrobook-sentence.is-active")?.classList.remove("is-active");
    const element = this.article.querySelector(`[data-sentence-id="${CSS.escape(active.id)}"]`);
    element?.classList.add("is-active");
    this.activeId = active.id;
    if (element && this.autoScroll && (forceScroll || performance.now() >= this.manualScrollUntil)) {
      const viewport = this.scroller.getBoundingClientRect();
      const rect = element.getBoundingClientRect();
      const upper = viewport.top + viewport.height * 0.3;
      const lower = viewport.top + viewport.height * 0.7;
      if (forceScroll || rect.top < upper || rect.bottom > lower) {
        element.scrollIntoView({ behavior: forceScroll ? "auto" : "smooth", block: "center" });
      }
    }
    return active;
  }
}
