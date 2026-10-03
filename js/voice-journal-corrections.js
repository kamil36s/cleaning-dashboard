export const DEFAULT_CORRECTION_SETTINGS = Object.freeze({
  confidenceGood: 0.7,
  confidenceWarning: 0.45,
  segmentLogprobThreshold: -1,
  unintelligibleMarker: "[niezrozumiałe]",
  rewindSeconds: 2,
});

const copy = (value) => JSON.parse(JSON.stringify(value));
const finiteOrNull = (value) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value)) ? Number(value) : null;

export function correctionSettings(value = {}) {
  const merged = { ...DEFAULT_CORRECTION_SETTINGS, ...(value && typeof value === "object" ? value : {}) };
  merged.confidenceGood = Math.max(0, Math.min(1, Number(merged.confidenceGood)));
  merged.confidenceWarning = Math.max(0, Math.min(merged.confidenceGood, Number(merged.confidenceWarning)));
  merged.segmentLogprobThreshold = Number.isFinite(Number(merged.segmentLogprobThreshold)) ? Number(merged.segmentLogprobThreshold) : -1;
  merged.unintelligibleMarker = String(merged.unintelligibleMarker || DEFAULT_CORRECTION_SETTINGS.unintelligibleMarker).slice(0, 80);
  merged.rewindSeconds = Math.max(0.5, Math.min(15, Number(merged.rewindSeconds) || 2));
  return merged;
}

export function normalizeCorrectionData(entry = {}) {
  const source = Array.isArray(entry.transcriptionData?.segments)
    ? entry.transcriptionData.segments
    : (Array.isArray(entry.transcriptSegments) ? entry.transcriptSegments : []);
  const segments = source.map((raw, segmentIndex) => {
    const id = String(raw.id || `segment-${segmentIndex + 1}`);
    const originalText = String(raw.originalText ?? raw.text ?? "").trim();
    const correctedText = String(raw.correctedText ?? raw.text ?? originalText).trim();
    return {
      ...copy(raw),
      id,
      start: finiteOrNull(raw.start),
      end: finiteOrNull(raw.end),
      text: String(raw.text ?? originalText),
      originalText,
      correctedText,
      avgLogprob: finiteOrNull(raw.avgLogprob ?? raw.avg_logprob),
      noSpeechProbability: finiteOrNull(raw.noSpeechProbability ?? raw.no_speech_prob),
      correctionStatus: String(raw.correctionStatus || "original"),
      words: (Array.isArray(raw.words) ? raw.words : []).map((word, wordIndex) => {
        const wordOriginal = String(word.originalText ?? word.text ?? word.word ?? "");
        return {
          ...copy(word),
          id: String(word.id || `${id}-word-${wordIndex + 1}`),
          text: String(word.text ?? wordOriginal),
          originalText: wordOriginal,
          correctedText: String(word.correctedText ?? word.text ?? wordOriginal),
          start: finiteOrNull(word.start),
          end: finiteOrNull(word.end),
          probability: finiteOrNull(word.probability),
          correctionStatus: String(word.correctionStatus || "original"),
          manuallyChanged: Boolean(word.manuallyChanged),
        };
      }),
    };
  });
  return {
    version: 1,
    engine: entry.transcriptionData?.engine || entry.engine || "openai-whisper",
    engineMetadata: copy(entry.transcriptionData?.engineMetadata || {}),
    segments,
  };
}

export function confidenceState(probability, settings = DEFAULT_CORRECTION_SETTINGS, status = "original") {
  if (["corrected", "approved", "unintelligible"].includes(status)) return status;
  if (probability === null || probability === undefined || probability === "" || !Number.isFinite(Number(probability))) return "unknown";
  const config = correctionSettings(settings);
  if (Number(probability) < config.confidenceWarning) return "danger";
  if (Number(probability) < config.confidenceGood) return "warning";
  return "good";
}

export function correctedTranscript(data) {
  return (data?.segments || []).map((segment) => segment.correctedText || segment.originalText || "").filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
}

export function correctionReviewItems(data, settings = DEFAULT_CORRECTION_SETTINGS, filter = "all") {
  const config = correctionSettings(settings);
  const items = [];
  for (const segment of data?.segments || []) {
    const segmentProblem = segment.start === null || segment.end === null || (segment.avgLogprob !== null && segment.avgLogprob < config.segmentLogprobThreshold);
    if (segmentProblem || ["review", "unintelligible", "corrected", "approved"].includes(segment.correctionStatus)) {
      items.push({ id: segment.id, segmentId: segment.id, kind: segment.correctionStatus === "original" ? "manual" : segment.correctionStatus, label: segment.correctedText || segment.originalText, start: segment.start, end: segment.end });
    }
    for (const word of segment.words || []) {
      const state = confidenceState(word.probability, config, word.correctionStatus);
      if (["danger", "warning", "corrected", "approved", "unintelligible"].includes(state) || word.correctionStatus === "review") {
        items.push({ id: word.id, segmentId: segment.id, wordId: word.id, kind: word.correctionStatus === "review" ? "manual" : state, label: word.correctedText || word.originalText, start: word.start ?? segment.start, end: word.end ?? segment.end });
      }
    }
  }
  if (filter === "all") return items;
  return items.filter((item) => item.kind === filter);
}

export function audioRangeForItem(item, segment, contextSeconds = 1) {
  const start = finiteOrNull(item?.start) ?? finiteOrNull(segment?.start) ?? 0;
  const end = finiteOrNull(item?.end) ?? finiteOrNull(segment?.end) ?? start;
  return { start: Math.max(0, start - contextSeconds), end: Math.max(start, end) + contextSeconds };
}

export function updateCorrectionItem(data, targetId, operation, value, at = new Date().toISOString()) {
  const next = copy(data);
  let changed = null;
  for (const segment of next.segments || []) {
    const item = segment.id === targetId ? segment : (segment.words || []).find((word) => word.id === targetId);
    if (!item) continue;
    const previous = item.correctedText ?? item.originalText ?? "";
    if (operation === "restore") {
      item.correctedText = item.originalText;
      item.correctionStatus = "original";
      item.manuallyChanged = false;
    } else if (operation === "unintelligible") {
      item.correctedText = String(value || DEFAULT_CORRECTION_SETTINGS.unintelligibleMarker);
      item.correctionStatus = "unintelligible";
      item.manuallyChanged = true;
    } else if (["review", "approved"].includes(operation)) {
      item.correctionStatus = operation;
    } else {
      item.correctedText = String(value ?? "");
      item.correctionStatus = "corrected";
      item.manuallyChanged = true;
    }
    if (item === segment && operation !== "review" && operation !== "approved") item.text = item.correctedText;
    if (item !== segment && !["review", "approved"].includes(operation)) {
      const wordTexts = segment.words.map((word) => word.correctedText ?? word.originalText ?? "");
      segment.correctedText = wordTexts.some((text) => /^\s/.test(text))
        ? wordTexts.join("").trim()
        : wordTexts.join(" ").trim();
      segment.text = segment.correctedText;
      segment.correctionStatus = "corrected";
    }
    changed = {
      at,
      operation,
      targetId,
      segmentId: segment.id,
      previousValue: previous,
      newValue: item.correctedText ?? previous,
    };
    break;
  }
  return { data: next, historyItem: changed };
}

export function restoreAllCorrections(data, at = new Date().toISOString()) {
  const next = copy(data);
  const history = [];
  for (const segment of next.segments || []) {
    const targets = [segment, ...(segment.words || [])];
    for (const item of targets) {
      if ((item.correctedText ?? item.originalText) === item.originalText && item.correctionStatus === "original") continue;
      history.push({ at, operation: "restore", targetId: item.id, segmentId: segment.id, previousValue: item.correctedText, newValue: item.originalText });
      item.correctedText = item.originalText;
      item.correctionStatus = "original";
      item.manuallyChanged = false;
    }
    segment.text = segment.originalText;
  }
  return { data: next, history };
}

const srtTime = (seconds, separator = ",") => {
  const milliseconds = Math.max(0, Math.round((Number(seconds) || 0) * 1000));
  const hours = Math.floor(milliseconds / 3600000);
  const minutes = Math.floor((milliseconds % 3600000) / 60000);
  const secs = Math.floor((milliseconds % 60000) / 1000);
  const ms = milliseconds % 1000;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}${separator}${String(ms).padStart(3, "0")}`;
};

export function exportCorrection(data, history = [], format = "txt", version = "corrected") {
  const segments = data?.segments || [];
  const textFor = (segment) => version === "original" ? segment.originalText : (segment.correctedText || segment.originalText);
  if (format === "json") return JSON.stringify({ version, engine: data?.engine, segments, history }, null, 2);
  if (format === "srt") return segments.map((segment, index) => `${index + 1}\n${srtTime(segment.start)} --> ${srtTime(segment.end)}\n${textFor(segment)}\n`).join("\n");
  if (format === "vtt") return `WEBVTT\n\n${segments.map((segment) => `${srtTime(segment.start, ".")} --> ${srtTime(segment.end, ".")}\n${textFor(segment)}\n`).join("\n")}`;
  return segments.map(textFor).filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
}

export function isTextEditingTarget(target) {
  return Boolean(target?.closest?.("input, textarea, select, [contenteditable='true']"));
}
