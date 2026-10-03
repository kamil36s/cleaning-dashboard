import { afterEach, describe, expect, it, vi } from "vitest";
import { journeyCollectionEntries, renderJourneyCollection } from "../js/live-workout-journey-page.js";
import { uploadJourneyPostcard } from "../js/live-workout-journey-api.js";

afterEach(() => vi.unstubAllGlobals());

const checkpoints = [
  { id: "santiago-001", index: 1, name: "Kraków", country: "Poland", routeDistanceKm: 0 },
  { id: "santiago-002", index: 2, name: "Skawina", country: "Poland", routeDistanceKm: 13.8 },
  { id: "santiago-003", index: 3, name: "Sekretne przyszłe miasto", country: "Poland", routeDistanceKm: 38.2 },
];

describe("journey postcard collection", () => {
  it("unlocks places from real route distance and associates uploaded postcards", () => {
    const entries = journeyCollectionEntries(checkpoints, 23.6, [{ checkpointId: "santiago-002", uploadedAt: 123 }]);
    expect(entries.map((item) => item.reached)).toEqual([true, true, false]);
    expect(entries[1].postcard.uploadedAt).toBe(123);
    const html = renderJourneyCollection(entries, "unlocked");
    expect(html).toContain('data-postcard-preview="santiago-002"');
    expect(html).toContain("Powiększ pocztówkę: Skawina");
  });

  it("shows the destination name but keeps a locked postcard image out of markup", () => {
    const entries = journeyCollectionEntries(checkpoints, 23.6, [{ checkpointId: "santiago-003", uploadedAt: 456 }]);
    const html = renderJourneyCollection(entries, "locked");
    expect(html).toContain("Sekretne przyszłe miasto");
    expect(html).toContain("ZABLOKOWANA · #3");
    expect(html).not.toContain("<img");
    expect(html).toContain("POCZTÓWKA ZAPIECZĘTOWANA");
    expect(html).toContain("ZMIEŃ ZAPIECZĘTOWANĄ");
    expect(html).not.toContain("/santiago-003/image");
  });
});

it("sends postcard JSON as a simple request and returns the saved version", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({ postcard: { checkpointId: "santiago-018", uploadedAt: 456 } }),
  });
  vi.stubGlobal("fetch", fetchMock);
  const file = new File(["postcard"], "jicin.png", { type: "image/png" });

  await expect(uploadJourneyPostcard("santiago-018", file)).resolves.toEqual({ checkpointId: "santiago-018", uploadedAt: 456 });
  const options = fetchMock.mock.calls[0][1];
  expect(options.method).toBe("POST");
  expect(options.headers).toBeUndefined();
  expect(JSON.parse(options.body)).toMatchObject({ checkpointId: "santiago-018", filename: "jicin.png", mimeType: "image/png" });
});
