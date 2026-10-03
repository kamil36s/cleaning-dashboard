import { describe, expect, it } from "vitest";

import {
  availableSymmetricLoads,
  buildMicroWorkout,
  calculateDumbbellLoad,
  progressionFromSessions,
  recoveryAdvice,
  rirLabel,
} from "../js/strength-model.js";

const equipment = [
  { item_type: "dumbbell_handle", measured_weight_kg: null },
  { item_type: "dumbbell_handle", measured_weight_kg: null },
  { item_type: "collar", measured_weight_kg: null, quantity: 4 },
  { item_type: "plate", nominal_weight_kg: 2.5, measured_weight_kg: null, quantity: 8 },
  { item_type: "plate", nominal_weight_kg: 1.25, measured_weight_kg: null, quantity: 4 },
];

describe("strength model", () => {
  it("maps RIR without pretending it is sensor-measured", () => {
    expect([5, 4, 2, 1, 0].map(rirLabel)).toEqual(["Easy", "Medium", "Hard", "Very hard", "Failure"]);
    expect(rirLabel(null)).toBe("Not provided");
  });

  it("does not produce a false exact load for unknown hardware", () => {
    expect(calculateDumbbellLoad(equipment, [2.5, 1.25])).toEqual({
      exact: false,
      platesWeightKg: 7.5,
      totalWeightKg: null,
      label: "7.5 kg plates + uncalibrated hardware",
    });
  });

  it("calculates calibrated handle, collars and plates", () => {
    const calibrated = equipment.map((item) => item.item_type === "dumbbell_handle"
      ? { ...item, measured_weight_kg: 2.1 }
      : item.item_type === "collar" ? { ...item, measured_weight_kg: 0.2 } : item);
    expect(calculateDumbbellLoad(calibrated, [2.5, 1.25])).toMatchObject({ exact: true, totalWeightKg: 10, platesWeightKg: 7.5 });
  });

  it("returns only loads supported symmetrically by the real plate inventory", () => {
    const loads = availableSymmetricLoads(equipment);
    expect(loads.map((item) => item.platesWeightKg)).toEqual([0, 2.5, 5, 7.5, 10, 12.5]);
  });

  it("compares total reps only at the same load and technique", () => {
    const previousSets = [{ reps: 10, loadIdentity: "plates:7.5", techniqueVariantId: "continuous" }, { reps: 9, loadIdentity: "plates:7.5", techniqueVariantId: "continuous" }];
    const currentSets = [{ reps: 10, loadIdentity: "plates:7.5", techniqueVariantId: "continuous" }, { reps: 10, loadIdentity: "plates:7.5", techniqueVariantId: "continuous" }];
    expect(progressionFromSessions({ previousSets, currentSets })).toMatchObject({ kind: "total_rep_pr", difference: 1 });
    expect(progressionFromSessions({ previousSets, currentSets: [{ reps: 20, loadIdentity: "plates:7.5", techniqueVariantId: "full-rep" }] }).kind).toBe("add_reps");
  });

  it("builds a short plan and keeps recovery advisory", () => {
    const exercises = [
      { id: "one", primaryMuscle: "abs", restSeconds: 60, executionMode: "reps" },
      { id: "two", primaryMuscle: "abs", restSeconds: 60, executionMode: "reps" },
    ];
    expect(buildMicroWorkout({ duration: 5, muscleGroup: "abs", exercises }).exercises).toHaveLength(1);
    expect(buildMicroWorkout({ duration: 10, muscleGroup: "abs", exercises }).exercises).toHaveLength(2);
    expect(recoveryAdvice({ status: "red" })).toMatchObject({ requiresConfirmation: true, manualSelectionAllowed: true });
  });
});
