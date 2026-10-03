export const STRENGTH_GROUPS = Object.freeze([
  { id: "abs", label: "ABS / CORE" },
  { id: "chest", label: "CHEST" },
  { id: "back", label: "BACK" },
  { id: "legs", label: "LEGS" },
  { id: "shoulders", label: "SHOULDERS" },
  { id: "biceps", label: "BICEPS" },
  { id: "triceps", label: "TRICEPS" },
]);

export const RIR_OPTIONS = Object.freeze([
  { value: 5, label: "Easy", range: "5+" },
  { value: 3, label: "Medium", range: "3–4" },
  { value: 2, label: "Hard", range: "2" },
  { value: 1, label: "Very hard", range: "1" },
  { value: 0, label: "Failure", range: "0" },
]);

export function rirLabel(value) {
  if (value === null || value === undefined || value === "") return "Not provided";
  const rir = Number(value);
  if (!Number.isFinite(rir)) return "Not provided";
  if (rir >= 5) return "Easy";
  if (rir >= 3) return "Medium";
  if (rir === 2) return "Hard";
  if (rir === 1) return "Very hard";
  return "Failure";
}

export function estimateMicroWorkoutMinutes(items = []) {
  const seconds = items.reduce((total, item, index) => {
    const sets = Math.max(1, Number(item.sets) || 1);
    const execution = Math.max(20, Number(item.executionSeconds) || (String(item.executionMode).startsWith("seconds") ? Number(item.repMin) || 40 : 45));
    const rests = Math.max(0, sets - 1) * Math.max(0, Number(item.restSeconds) || 0);
    const transition = index ? 60 : 45;
    return total + sets * execution + rests + transition;
  }, 0);
  return Math.max(1, Math.ceil(seconds / 60));
}

function durationSetBudget(duration) {
  if (duration <= 5) return [2];
  if (duration <= 10) return [2, 2];
  if (duration <= 15) return [3, 3];
  return [3, 3];
}

export function buildMicroWorkout({ duration = 5, muscleGroup = "abs", exercises = [], recentExerciseIds = [] } = {}) {
  const available = exercises.filter((item) => item.primaryMuscle === muscleGroup);
  const ordered = [...available].sort((left, right) => {
    const leftRecent = recentExerciseIds.indexOf(left.id);
    const rightRecent = recentExerciseIds.indexOf(right.id);
    return (leftRecent < 0 ? -1000 : -leftRecent) - (rightRecent < 0 ? -1000 : -rightRecent);
  });
  const budgets = durationSetBudget(Number(duration));
  const plan = ordered.slice(0, budgets.length).map((exercise, index) => ({ ...exercise, sets: budgets[index] }));
  return { duration: Number(duration), muscleGroup, exercises: plan, estimatedMinutes: estimateMicroWorkoutMinutes(plan) };
}

export function chooseSuggestedMuscle(scoreboard = [], recovery = []) {
  const recoveryMap = new Map(recovery.map((item) => [item.muscleGroup, item.status]));
  const scored = scoreboard.map((item) => ({
    ...item,
    score: (item.muscle_group === "abs" ? 100 : Number(item.priority) || 0)
      + Math.max(0, Number(item.toMinimum) || 0) * 20
      + Math.max(0, Number(item.toTarget) || 0) * 2
      - (recoveryMap.get(item.muscle_group) === "red" ? 1000 : 0)
      - (recoveryMap.get(item.muscle_group) === "yellow" ? 10 : 0),
  }));
  return scored.sort((left, right) => right.score - left.score)[0]?.muscle_group || "abs";
}

export function progressionFromSessions({ previousSets = [], currentSets = [], repMax = 15, plannedSets = 3 } = {}) {
  const comparable = (left, right) => left.techniqueVariantId === right.techniqueVariantId
    && left.loadIdentity === right.loadIdentity;
  if (!currentSets.length) return { kind: "none" };
  const anchor = currentSets[0];
  const current = currentSets.filter((item) => comparable(anchor, item));
  const previous = previousSets.filter((item) => comparable(anchor, item));
  const currentTotal = current.reduce((sum, item) => sum + Number(item.reps || 0), 0);
  const previousTotal = previous.reduce((sum, item) => sum + Number(item.reps || 0), 0);
  const reachedTop = current.length >= Math.max(1, Number(plannedSets) || 1)
    && current.every((item) => Number(item.reps || 0) >= Number(repMax))
    && current.every((item) => item.rir == null || (Number(item.rir) >= 1 && Number(item.rir) <= 2));
  if (reachedTop) return { kind: "level_up", currentTotal, previousTotal };
  if (previous.length && currentTotal > previousTotal) return { kind: "total_rep_pr", difference: currentTotal - previousTotal, currentTotal, previousTotal };
  return { kind: "add_reps", targetTotal: Math.max(currentTotal, previousTotal) + 1, currentTotal, previousTotal };
}

const round = (value) => Math.round(value * 1000) / 1000;

export function calculateDumbbellLoad(items = [], platesPerSide = []) {
  const handles = items.filter((item) => item.item_type === "dumbbell_handle");
  const collars = items.find((item) => item.item_type === "collar");
  const handleWeights = handles.map((item) => item.measured_weight_kg).filter((value) => value != null).map(Number);
  const handleKnown = handles.length > 0
    && handleWeights.length === handles.length
    && new Set(handleWeights.map((value) => round(value))).size === 1;
  const collarKnown = Boolean(collars && collars.measured_weight_kg != null);
  const platesWeight = round(platesPerSide.reduce((sum, value) => sum + Number(value || 0), 0) * 2);
  const hardwareWeight = (handleKnown ? handleWeights[0] : 0) + (collarKnown ? Number(collars.measured_weight_kg) * 2 : 0);
  const exact = handleKnown && collarKnown;
  return {
    exact,
    platesWeightKg: platesWeight,
    totalWeightKg: exact ? round(platesWeight + hardwareWeight) : null,
    label: exact
      ? `${round(platesWeight + hardwareWeight)} kg per dumbbell`
      : `${platesWeight} kg plates + uncalibrated hardware`,
  };
}

export function availableSymmetricLoads(items = [], { dumbbellCount = 2 } = {}) {
  const plates = items.filter((item) => item.item_type === "plate" && Number(item.quantity) > 0);
  const unitSides = Math.max(1, Number(dumbbellCount) || 1) * 2;
  const options = [0];
  for (const plate of plates) {
    const weight = Number(plate.measured_weight_kg ?? plate.nominal_weight_kg);
    if (!Number.isFinite(weight) || weight <= 0) continue;
    const pairsPerSide = Math.floor(Number(plate.quantity) / unitSides);
    const snapshot = [...options];
    for (let count = 1; count <= pairsPerSide; count += 1) {
      snapshot.forEach((base) => options.push(round(base + weight * count * 2)));
    }
  }
  return [...new Set(options)].sort((left, right) => left - right).map((platesWeightKg) => {
    const side = [];
    let remaining = platesWeightKg / 2;
    [...plates].sort((a, b) => Number(b.nominal_weight_kg) - Number(a.nominal_weight_kg)).forEach((plate) => {
      const weight = Number(plate.measured_weight_kg ?? plate.nominal_weight_kg);
      const max = Math.floor(Number(plate.quantity) / unitSides);
      let count = 0;
      while (count < max && remaining + 0.0001 >= weight) { side.push(weight); remaining = round(remaining - weight); count += 1; }
    });
    return { platesWeightKg, platesPerSide: side, ...calculateDumbbellLoad(items, side) };
  });
}

export function recoveryAdvice(recovery) {
  if (!recovery || recovery.status === "green") return { status: "green", label: "Ready", requiresConfirmation: false, manualSelectionAllowed: true };
  if (recovery.status === "red") return { status: "red", label: "Elevated fatigue", requiresConfirmation: true, manualSelectionAllowed: true };
  return { status: "yellow", label: "Recently trained", requiresConfirmation: false, manualSelectionAllowed: true };
}
