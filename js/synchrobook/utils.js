export function formatTime(value) {
  const seconds = Math.max(0, Number(value) || 0);
  const whole = Math.floor(seconds);
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const remainder = whole % 60;
  return hours ? `${hours}:${String(minutes).padStart(2, "0")}:${String(remainder).padStart(2, "0")}` : `${minutes}:${String(remainder).padStart(2, "0")}`;
}

export function chapterIdAtTime(alignment, currentTime, fallbackChapterId = null) {
  const time = Number(currentTime);
  if (!Number.isFinite(time)) return fallbackChapterId;
  let currentChapterId = null;
  for (const chapter of alignment?.chapters || []) {
    const firstStart = (chapter.sentences || []).find(
      (sentence) => sentence.start != null && Number.isFinite(Number(sentence.start)),
    )?.start;
    if (firstStart == null) continue;
    if (Number(firstStart) > time) break;
    currentChapterId = chapter.id;
  }
  return currentChapterId || fallbackChapterId || null;
}

export function chapterEndTime(alignment, chapterId, audiobookDuration = null) {
  const chapters = alignment?.chapters || [];
  const chapterIndex = chapters.findIndex((chapter) => chapter.id === chapterId);
  if (chapterIndex < 0) return null;
  for (let index = chapterIndex + 1; index < chapters.length; index += 1) {
    const nextStart = (chapters[index].sentences || []).find(
      (sentence) => sentence.start != null && Number.isFinite(Number(sentence.start)),
    )?.start;
    if (nextStart != null) return Number(nextStart);
  }
  let end = null;
  for (const sentence of chapters[chapterIndex].sentences || []) {
    const value = sentence.end ?? sentence.start;
    if (value != null && Number.isFinite(Number(value))) end = Math.max(end ?? 0, Number(value));
  }
  const duration = Number(audiobookDuration);
  if (chapterIndex === chapters.length - 1 && Number.isFinite(duration) && duration > 0) {
    return Math.max(end ?? 0, duration);
  }
  return end;
}

export function realTimeRemaining(currentTime, endTime, playbackRate = 1) {
  const current = Number(currentTime);
  const end = Number(endTime);
  const rate = Number(playbackRate);
  if (![current, end, rate].every(Number.isFinite) || rate <= 0) return null;
  return Math.max(0, (end - current) / rate);
}

export function formatRemaining(value) {
  if (!Number.isFinite(value)) return "—";
  return formatTime(Math.ceil(Math.max(0, value)));
}

export function playbackRemainingTimes({ alignment, currentTime, duration, playbackRate, fallbackChapterId = null }) {
  const chapterId = chapterIdAtTime(alignment, currentTime, fallbackChapterId);
  const chapterEnd = chapterEndTime(alignment, chapterId, duration);
  return {
    chapterId,
    chapter: realTimeRemaining(currentTime, chapterEnd, playbackRate),
    book: realTimeRemaining(currentTime, duration, playbackRate),
  };
}

const PROCESSING_JOB_STATES = new Set([
  "QUEUED", "BOOK_PROCESSING", "EPUB_PROCESSING", "AUDIO_PREPARING",
  "AUDIO_MERGING", "TRANSCRIBING", "ALIGNING", "FINALIZING",
]);

function median(values) {
  if (!values.length) return null;
  const sorted = [...values].sort((left, right) => left - right);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
}

export function estimateQueueRemainingSeconds(jobs, now = Date.now()) {
  const rows = Array.isArray(jobs) ? jobs : [];
  const active = rows.filter((job) => PROCESSING_JOB_STATES.has(job?.status));
  if (!active.length) return null;

  const terminal = rows
    .filter((job) => ["READY", "ERROR"].includes(job?.status))
    .map((job) => ({ job, created: Date.parse(job.createdAt || ""), ended: Date.parse(job.updatedAt || "") }))
    .filter(({ created, ended }) => Number.isFinite(created) && Number.isFinite(ended) && ended > created)
    .sort((left, right) => left.ended - right.ended);
  const historicalByKind = new Map();
  let previousEnd = null;
  for (const entry of terminal) {
    const started = Math.max(entry.created, previousEnd ?? entry.created);
    const duration = (entry.ended - started) / 1000;
    if (entry.job.status === "READY" && duration >= 10) {
      const durations = historicalByKind.get(entry.job.kind) || [];
      durations.push(duration);
      historicalByKind.set(entry.job.kind, durations);
    }
    previousEnd = Math.max(previousEnd ?? entry.ended, entry.ended);
  }
  const allHistorical = [...historicalByKind.values()].flat();
  const globalTypical = median(allHistorical);
  const lastFinishedAt = terminal.reduce((latest, entry) => Math.max(latest, entry.ended), -Infinity);

  function activeElapsed(job) {
    const created = Date.parse(job?.createdAt || "");
    if (!Number.isFinite(created)) return null;
    const started = Math.max(created, lastFinishedAt);
    return now > started ? (now - started) / 1000 : null;
  }

  const liveTotals = active.flatMap((job) => {
    const progress = Number(job.progress);
    const elapsed = activeElapsed(job);
    if (job.status === "QUEUED" || !Number.isFinite(progress) || progress < 2 || progress >= 100 || !Number.isFinite(elapsed) || elapsed < 5) return [];
    return [elapsed / (progress / 100)];
  });
  const liveTypical = median(liveTotals);

  let total = 0;
  for (const job of active) {
    const history = median(historicalByKind.get(job.kind) || []) ?? globalTypical;
    const progress = Math.min(99, Math.max(0, Number(job.progress) || 0));
    const elapsed = activeElapsed(job);
    const liveTotal = job.status !== "QUEUED" && progress >= 2 && Number.isFinite(elapsed) && elapsed >= 5
      ? elapsed / (progress / 100)
      : null;
    const expectedTotal = history ?? liveTotal ?? liveTypical;
    if (!Number.isFinite(expectedTotal)) return null;
    total += job.status === "QUEUED" ? expectedTotal : expectedTotal * (1 - progress / 100);
  }
  return Math.max(0, total);
}

export function formatQueueEstimate(seconds) {
  if (!Number.isFinite(seconds)) return "Pozostało: obliczanie…";
  if (seconds < 60) return "Pozostało: mniej niż 1 min";
  const roundedMinutes = Math.max(1, Math.ceil(seconds / 300) * 5);
  if (roundedMinutes < 60) return `Pozostało: około ${roundedMinutes} min`;
  const hours = Math.floor(roundedMinutes / 60);
  const minutes = roundedMinutes % 60;
  return `Pozostało: około ${hours} godz.${minutes ? ` ${minutes} min` : ""}`;
}

export function findActiveSentenceIndex(sentences, currentTime) {
  let low = 0;
  let high = sentences.length - 1;
  let answer = -1;
  while (low <= high) {
    const middle = (low + high) >> 1;
    if (Number(sentences[middle].start) <= currentTime) {
      answer = middle;
      low = middle + 1;
    } else {
      high = middle - 1;
    }
  }
  return answer;
}

export const wait = (milliseconds) => new Promise((resolve) => window.setTimeout(resolve, milliseconds));
