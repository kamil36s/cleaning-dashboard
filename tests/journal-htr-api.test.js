import { describe, expect, it, vi } from "vitest";

import {
  deleteHtrModel,
  startHtrServer,
  stopHtrServer,
} from "../js/journal-htr-api.js";

describe("Journal HTR model API", () => {
  it("requires an explicit confirmed DELETE for a model", async () => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      json: async () => ({ ok: true, deletedModelId: "duplicate-model" }),
    }));

    const result = await deleteHtrModel("duplicate-model", fetchImpl);

    expect(result.ok).toBe(true);
    expect(fetchImpl).toHaveBeenCalledWith(
      "/api/journal-htr/models/duplicate-model?confirm=delete",
      expect.objectContaining({ method: "DELETE", cache: "no-store" }),
    );
  });

  it.each([
    ["start", startHtrServer],
    ["stop", stopHtrServer],
  ])("uses a dedicated POST endpoint to %s the OCR server", async (action, call) => {
    const fetchImpl = vi.fn(async () => ({
      ok: true,
      json: async () => ({ runtime: { state: `${action}ing` } }),
    }));

    await call(fetchImpl);

    expect(fetchImpl).toHaveBeenCalledWith(
      `/api/journal-htr/server/${action}`,
      expect.objectContaining({ method: "POST", cache: "no-store" }),
    );
  });
});
