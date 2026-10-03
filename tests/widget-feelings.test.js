import { beforeEach, describe, expect, it, vi } from "vitest";

const emotion = { id: "calm", name: "Calm", description: "free of worry", quadrant: "low_pleasant", color: "#49dda0", shape: "petal", x: 6, y: 6 };
const checkin = { id: "one", occurredAt: "2026-09-23T10:00", timezone: "Europe/Warsaw", note: "Quiet morning", source: "dashboard", emotion, emotions: [emotion], tags: [{ id: "home", name: "Home" }] };

function responseFor(url) {
  if (url.includes("/emotions")) return { ok: true, emotions: [emotion] };
  if (url.includes("/tags")) return { ok: true, tags: [{ id: "home", name: "Home", category: "place", usageCount: 1 }] };
  if (url.includes("/insights")) return { ok: true, total: 1, quadrants: [], emotions: [], timeOfDay: {}, dayOfWeek: {}, trend: [], heatmap: [], tagAssociations: [], emotionAssociations: [] };
  return { ok: true, checkins: [checkin], count: 1 };
}

describe("How I Feel widget", () => {
  beforeEach(() => {
    vi.resetModules();
    document.body.innerHTML = `<section id="feelings-card"><button id="feelings-check-in">Check in</button><div id="feelings-widget-root"></div></section>`;
    global.fetch = vi.fn(async (url) => ({ ok: true, json: async () => responseFor(String(url)) }));
  });

  it("renders the latest real check-in and opens the quadrant workspace", async () => {
    await import("../js/widget-feelings.js?test=widget");
    await vi.waitFor(() => expect(document.querySelector("#feelings-widget-root").textContent).toContain("Calm"));
    document.querySelector("#feelings-check-in").click();
    await vi.waitFor(() => expect(document.querySelector(".feelings-quadrant-field")).not.toBeNull());
    expect(document.querySelectorAll(".feelings-quadrant")).toHaveLength(4);
    document.querySelector(".feelings-quadrant.is-low_pleasant").click();
    const node = document.querySelector(".feelings-emotion-node");
    expect(node.dataset.definition).toBe("free of worry");
    expect(node.getAttribute("aria-label")).toContain("Calm: free of worry");
    expect(node.classList.contains("shape-petal")).toBe(true);
    expect(node.style.gridColumn).not.toBe("");
    expect(document.querySelectorAll(".feelings-meter-pan")).toHaveLength(4);
    const zoom = document.querySelector(".feelings-meter-zoom span");
    document.querySelector("[data-meter-viewport]").dispatchEvent(new WheelEvent("wheel", { bubbles: true, cancelable: true, deltaY: -100, clientX: 400, clientY: 300 }));
    expect(zoom.textContent).toBe("199%");
    expect(document.querySelector(".feelings-widget-tags")).toBeNull();
    expect(document.querySelector(".feelings-widget-note")).toBeNull();
    expect(document.querySelector(".feelings-widget-week > p")).toBeNull();
    expect(global.fetch).toHaveBeenCalledWith(expect.stringContaining("/api/feelings/checkins"), expect.any(Object));
  });
});
