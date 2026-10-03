import { describe, expect, it } from "vitest";

import {
  buildCardioCalorieChartSeries,
  buildCardioCaloriePeriodSeries,
  buildCardioEfficiencyRanking,
  buildCyclingCalorieRanking,
  calculateLiveCalorieRank,
  calorieRankMedal,
  calorieRankTier,
  summarizeCardioCalorieTrend,
} from "../js/live-workout-ranking.js";

const timestamp = (value) => new Date(`${value}T12:00:00`).getTime();

describe("Live Workout calorie ranking", () => {
  it("sums cycling and walking by local day while ignoring zero and strength", () => {
    const ranking = buildCyclingCalorieRanking([
      { status: "finished", workout_type: "indoor_cycling", started_at: timestamp("2026-09-20"), duration_seconds: 1800, active_calories: 120 },
      { status: "finished", workout_type: "indoor_cycling", started_at: timestamp("2026-09-20"), duration_seconds: 1200, active_calories: 80.5 },
      { status: "finished", workout_type: "virtual_walk", started_at: timestamp("2026-09-20"), duration_seconds: 3600, active_calories: 500 },
      { status: "finished", workout_type: "strength", started_at: timestamp("2026-09-21"), active_calories: 400 },
      { status: "finished", workout_type: "indoor_cycling", started_at: timestamp("2026-09-19"), active_calories: 0 },
      { status: "running", workout_type: "indoor_cycling", started_at: timestamp("2026-09-22"), active_calories: 900 },
    ]);

    expect(ranking).toEqual([{
      date: "2026-09-20",
      activeCalories: 700.5,
      cyclingCalories: 200.5,
      walkingCalories: 500,
      durationSeconds: 6600,
      sessionCount: 3,
      cyclingSessionCount: 2,
      walkingSessionCount: 1,
      position: 1,
    }]);
  });

  it("adds live calories to today's stored total and requires a strict beat", () => {
    const days = [
      { date: "2026-09-20", active_calories: 500, session_count: 1 },
      { date: "2026-09-21", active_calories: 300, session_count: 1 },
      { date: "2026-09-23", active_calories: 100, session_count: 1 },
    ];

    expect(calculateLiveCalorieRank(days, { date: "2026-09-23", liveCalories: 199.9 })).toMatchObject({
      position: 3,
      todayCalories: 299.9,
      caloriesToNext: 0.2,
    });
    expect(calculateLiveCalorieRank(days, { date: "2026-09-23", liveCalories: 200 })).toMatchObject({
      position: 3,
      todayCalories: 300,
      caloriesToNext: 0.1,
    });
    expect(calculateLiveCalorieRank(days, { date: "2026-09-23", liveCalories: 200.1 })).toMatchObject({
      position: 2,
      todayCalories: 300.1,
      caloriesToNext: 200,
    });
  });

  it("ranks cardio days by kcal per hour and ignores days without duration", () => {
    const ranking = buildCardioEfficiencyRanking([
      { date: "2026-09-20", active_calories: 600, duration_seconds: 7200 },
      { date: "2026-09-21", active_calories: 400, duration_seconds: 3600 },
      { date: "2026-09-22", active_calories: 900, duration_seconds: 0 },
    ]);

    expect(ranking.map((day) => ({ date: day.date, caloriesPerHour: day.caloriesPerHour, position: day.position }))).toEqual([
      { date: "2026-09-21", caloriesPerHour: 400, position: 1 },
      { date: "2026-09-20", caloriesPerHour: 300, position: 2 },
    ]);
  });

  it("assigns special tiers and medals to top positions", () => {
    expect(calorieRankTier(11)).toBe("standard");
    expect(calorieRankTier(10)).toBe("top10");
    expect(calorieRankTier(3)).toBe("podium");
    expect([1, 2, 3].map(calorieRankMedal)).toEqual(["🥇", "🥈", "🥉"]);
  });

  it("adds an active walk to the total and walking share", () => {
    const rank = calculateLiveCalorieRank([
      { date: "2026-09-23", active_calories: 300, cycling_calories: 200, walking_calories: 100 },
    ], { date: "2026-09-23", liveCalories: 100, workoutType: "virtual_walk" });

    expect(rank).toMatchObject({
      todayCalories: 400,
      todayCyclingCalories: 200,
      todayWalkingCalories: 200,
      cyclingPercent: 50,
      walkingPercent: 50,
    });
  });

  it("builds a 30-day calendar series with zero days and MA7", () => {
    const series = buildCardioCalorieChartSeries([
      { date: "2026-09-21", active_calories: 70, cycling_calories: 50, walking_calories: 20 },
      { date: "2026-09-23", active_calories: 140, cycling_calories: 140, walking_calories: 0 },
    ], { endDate: "2026-09-23", dayCount: 3 });

    expect(series).toEqual([
      { date: "2026-09-21", activeCalories: 70, cyclingCalories: 50, walkingCalories: 20, movingAverage: 70 },
      { date: "2026-09-22", activeCalories: 0, cyclingCalories: 0, walkingCalories: 0, movingAverage: 35 },
      { date: "2026-09-23", activeCalories: 140, cyclingCalories: 140, walkingCalories: 0, movingAverage: 70 },
    ]);
  });

  it("builds period cardio points as calendar-day averages", () => {
    const series = buildCardioCaloriePeriodSeries([
      { date: "2026-09-21", active_calories: 70, cycling_calories: 50, walking_calories: 20 },
      { date: "2026-09-23", active_calories: 140, cycling_calories: 140, walking_calories: 0 },
    ], { endDate: "2026-09-23", dayCount: 3, periodDays: 3 });

    expect(series).toEqual([{
      date: "2026-09-23",
      periodStart: "2026-09-21",
      periodEnd: "2026-09-23",
      activeCalories: 70,
      cyclingCalories: 63.33,
      walkingCalories: 6.67,
      activeDayCount: 2,
      movingAverage: 0,
    }]);
  });

  it("summarizes MA7 direction, regularity and cardio mix", () => {
    const series = Array.from({ length: 14 }, (_, index) => ({
      activeCalories: index < 7 ? 50 : 100,
      cyclingCalories: index < 7 ? 50 : 75,
      walkingCalories: index < 7 ? 0 : 25,
      movingAverage: index < 7 ? 50 : 100,
    }));

    expect(summarizeCardioCalorieTrend(series)).toMatchObject({
      latestMa7: 100,
      previousMa7: 50,
      delta: 50,
      changePercent: 100,
      direction: "up",
      recentActiveDays: 7,
      previousActiveDays: 7,
      cyclingPercent: 75,
      walkingPercent: 25,
    });
  });
});
