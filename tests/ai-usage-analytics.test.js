import { describe, expect, it } from "vitest";
import {
  aggregateBurnHistory,
  buildQuotaSeries,
  estimateExhaustion,
  simulatePlans,
} from "../js/ai-usage-analytics.js";

describe("AI Usage analytics", () => {
  it("estimates one active hour left from 25% remaining at 25% per hour", () => {
    const result = estimateExhaustion({
      remaining: 25,
      burnPercent: 25,
      activeSeconds: 3600,
      resetAt: "2026-09-12T14:00:00Z",
      now: Date.parse("2026-09-12T12:00:00Z"),
      sampleCount: 1,
    });
    expect(result.activeHoursLeft).toBe(1);
    expect(result.status).toBe("likely_to_hit_limit");
  });

  it("returns not enough data without burn", () => {
    expect(estimateExhaustion({ remaining: 25, burnPercent: 0, activeSeconds: 3600 }).status)
      .toBe("not_enough_data");
  });

  it("marks exhaustion after reset as safe", () => {
    const result = estimateExhaustion({
      remaining: 100,
      burnPercent: 10,
      activeSeconds: 3600,
      resetAt: "2026-09-12T14:00:00Z",
      now: Date.parse("2026-09-12T12:00:00Z"),
    });
    expect(result.status).toBe("safe_until_reset");
  });

  it("scales burn and VAT for Plus, Pro 5X and Pro 20X", () => {
    const plans = simulatePlans({
      currentBurnPerActiveHour: 20,
      currentPlanName: "ChatGPT Plus",
      vatRate: 0.23,
      usdPlnRate: 4,
      projectedWeeklyUsage: 100,
    });
    expect(plans.map((plan) => plan.multiplier)).toEqual([1, 5, 20]);
    expect(plans.map((plan) => plan.equivalentBurnPerHour)).toEqual([20, 4, 1]);
    expect(plans.map((plan) => plan.grossMonthlyUsd)).toEqual([24.6, 123, 246]);
  });

  it("aggregates burn into local daily buckets", () => {
    const now = new Date(2026, 8, 12, 20).getTime();
    const history = [{
      provider: "codex", group: "main", checkedAt: new Date(2026, 8, 12, 13).toISOString(),
      fiveHourBurn: 6, weeklyBurn: 2,
    }, {
      provider: "codex", group: "main", checkedAt: new Date(2026, 8, 12, 13, 30).toISOString(),
      fiveHourBurn: 5, weeklyBurn: 1,
    }];
    const buckets = aggregateBurnHistory(history, { provider: "codex", group: "main", now });
    expect(buckets[13]).toMatchObject({ fiveHour: 11, weekly: 3 });
  });

  it("uses only sessions from the current plan when calculating burn rate", async () => {
    const { sessionRate } = await import("../js/ai-usage-analytics.js");
    const rate = sessionRate(
      { provider: "codex", group: "main" },
      [
        { provider: "codex", group: "main", session_start: "2026-09-16T09:00:00Z", weekly_burn: 20, duration_seconds: 3600 },
        { provider: "codex", group: "main", session_start: "2026-09-16T11:00:00Z", weekly_burn: 4, duration_seconds: 1800 },
      ],
      "weekly",
      { since: "2026-09-16T10:10:54Z" },
    );
    expect(rate).toEqual({ burnPercent: 4, activeSeconds: 1800, sampleCount: 1 });
  });

  it("splits quota lines at reset markers", () => {
    const now = Date.parse("2026-09-12T13:00:00Z");
    const row = (time, remaining) => ({
      provider: "codex", group: "main", checkedAt: time, status: "connected",
      fiveHour: { remaining },
    });
    const result = buildQuotaSeries([
      row("2026-09-12T10:00:00Z", 30),
      row("2026-09-12T11:00:00Z", 10),
      row("2026-09-12T12:00:00Z", 100),
      row("2026-09-12T13:00:00Z", 90),
    ], { provider: "codex", group: "main", windowKey: "fiveHour", now, rangeHours: 5 });
    expect(result.segments).toHaveLength(2);
    expect(result.resets).toHaveLength(1);
  });

  it("marks a small refill to 100% when the provider reset timestamp changes", () => {
    const now = Date.parse("2026-09-12T13:00:00Z");
    const result = buildQuotaSeries([
      {
        provider: "codex", group: "main", checkedAt: "2026-09-12T12:00:00Z", status: "connected",
        fiveHour: { remaining: 92, resetAt: "2026-09-12T12:30:00Z" },
      },
      {
        provider: "codex", group: "main", checkedAt: "2026-09-12T13:00:00Z", status: "connected",
        fiveHour: { remaining: 100, resetAt: "2026-09-12T18:00:00Z" },
      },
    ], { provider: "codex", group: "main", windowKey: "fiveHour", now, rangeHours: 5 });
    expect(result.resets).toHaveLength(1);
  });

  it("splits quota history at a plan upgrade without calling it a reset", () => {
    const now = Date.parse("2026-09-16T11:00:00Z");
    const result = buildQuotaSeries([
      {
        provider: "codex", group: "main", checkedAt: "2026-09-16T10:00:00Z", status: "connected",
        weekly: { remaining: 8, resetAt: "2026-09-19T09:35:21Z" },
      },
      {
        provider: "codex", group: "main", checkedAt: "2026-09-16T10:11:00Z", status: "connected",
        weekly: { remaining: 100, resetAt: "2026-09-23T10:11:00Z" },
      },
    ], {
      provider: "codex",
      group: "main",
      windowKey: "weekly",
      now,
      rangeHours: 5,
      planChanges: [{
        provider: "codex",
        group: "main",
        activatedAt: "2026-09-16T10:10:54.914025Z",
        fromPlanName: "ChatGPT Plus",
        toPlanName: "ChatGPT Pro 5X",
        quotaMultiplier: 5,
      }],
    });
    expect(result.segments).toHaveLength(2);
    expect(result.resets).toHaveLength(0);
    expect(result.planChanges).toHaveLength(1);
    expect(result.points[1].usedSincePrevious).toBe(0);
  });
});
