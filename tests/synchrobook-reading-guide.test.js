import { describe, expect, it, vi } from "vitest";
import { ReadingGuideRuntime, buildCommentaryRangeIndex, resolveCommentaryChunk, sourceAnchorOrder } from "../js/synchrobook/reading-guide/runtime.js";
import { appendArgumentAnalysis, appendArgumentMap } from "../js/synchrobook/reading-guide/ui.js";

const book = { chapters: [{ id: "ch01", paragraphs: [{ sentences: [
  { id: "s1" }, { id: "s2" }, { id: "s3" }, { id: "s4" },
] }] }] };
const chunks = [
  { id: "c1", start_source_id: "s1", end_source_id: "s3" },
  { id: "c2", start_source_id: "s4", end_source_id: "s4" },
];

describe("Synchrobook Reading Guide runtime", () => {
  it("resolves imported start/end anchors with an indexed lookup", () => {
    const order = sourceAnchorOrder(book); const index = buildCommentaryRangeIndex(book, chunks);
    expect(resolveCommentaryChunk(index, "s2", order)?.id).toBe("c1");
    expect(resolveCommentaryChunk(index, "s4", order)?.id).toBe("c2");
    expect(resolveCommentaryChunk(index, "missing", order)).toBeNull();
  });

  it("does not rerender within a chunk and updates at a boundary", () => {
    const render = vi.fn(); const runtime = new ReadingGuideRuntime({ onChange: render });
    runtime.setData(book, chunks); render.mockClear();
    runtime.sync("s1"); runtime.sync("s2"); runtime.sync("s3");
    expect(render).toHaveBeenCalledTimes(1);
    runtime.sync("s4"); expect(render).toHaveBeenCalledTimes(2);
  });

  it("manual navigation disables Follow Reading and restoring it resolves current anchor", () => {
    const runtime = new ReadingGuideRuntime(); runtime.setData(book, chunks); runtime.sync("s4");
    runtime.previous(); expect(runtime.followReading).toBe(false); expect(runtime.current()?.id).toBe("c1");
    runtime.sync("s4"); expect(runtime.current()?.id).toBe("c1");
    runtime.follow(); expect(runtime.followReading).toBe(true); expect(runtime.current()?.id).toBe("c2");
  });

  it("a book without guide data remains unresolved", () => {
    const runtime = new ReadingGuideRuntime(); runtime.setData(book, []);
    expect(runtime.sync("s1")).toBe(false); expect(runtime.current()).toBeNull();
  });
});

describe("Synchrobook Reading Guide renderers", () => {
  it("renders argument analysis as readable sections instead of raw JSON", () => {
    const container = document.createElement("div");
    appendArgumentAnalysis(container, {
      premises: ["Pierwsza przesłanka", "Druga przesłanka"],
      implicit_premises: [],
      steps: ["Krok rozumowania"],
      conclusion: "Wniosek",
      assessment_note: "Ocena",
    });
    expect(container.querySelector("pre")).toBeNull();
    expect(container.querySelector('[data-argument-field="premises"]')?.textContent).toContain("Pierwsza przesłanka");
    expect(container.querySelector('[data-argument-field="steps"]')?.textContent).toContain("Krok rozumowania");
    expect(container.querySelector('[data-argument-field="conclusion"]')?.textContent).toContain("Wniosek");
    expect(container.querySelector('[data-argument-field="assessment_note"]')?.textContent).toContain("Ocena");
    expect(container.querySelector('[data-argument-field="implicit_premises"]')).toBeNull();
  });

  it("renders an argument map as claims and relations instead of raw JSON", () => {
    const container = document.createElement("div");
    appendArgumentMap(container, {
      nodes: [
        { id: "N1", label: "Pierwsza teza", source_range: "P I–III" },
        { id: "N2", label: "Druga teza", source_range: "P IV–V" },
      ],
      edges: [{ from: "N1", relation: "supports", to: "N2" }],
    });
    expect(container.querySelector("pre")).toBeNull();
    expect(container.querySelector('[data-map-node="N1"]')?.textContent).toContain("Pierwsza teza");
    expect(container.querySelector('[data-map-node="N1"]')?.textContent).toContain("P I–III");
    expect(container.querySelector(".synchrobook-guide-map-relations")?.textContent).toContain("N1 → N2");
    expect(container.querySelector(".synchrobook-guide-map-relations")?.textContent).toContain("supports");
  });
});
