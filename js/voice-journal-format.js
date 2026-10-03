export const VOICE_JOURNAL_ACCEPT = ".aac,.m4a,.mp3,.wav,.ogg,.webm,.flac,audio/aac,audio/x-aac,audio/vnd.dlna.adts,audio/mp4,audio/mpeg,audio/wav,audio/ogg,audio/webm,audio/flac";

function pad(value) {
  return String(value).padStart(2, "0");
}

export function audioFileExtension(file) {
  return String(file?.name || "").split(".").pop()?.toLowerCase() || "";
}

export function voiceJournalEntryTitle(entry) {
  return String(entry?.title || "").trim()
    || String(entry?.originalFilename || "").trim()
    || "Bez tytułu";
}

export function formatVoiceJournalBytes(value) {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "-";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toLocaleString("pl-PL", { maximumFractionDigits: 1 })} KB`;
  return `${(bytes / 1024 ** 2).toLocaleString("pl-PL", { maximumFractionDigits: 2 })} MB`;
}

export function formatVoiceJournalDuration(value) {
  const seconds = Number(value);
  if (!Number.isFinite(seconds) || seconds < 0) return "-";
  const rounded = Math.round(seconds);
  return `${Math.floor(rounded / 60)}:${pad(rounded % 60)}`;
}

export function formatVoiceJournalTimestamp(value) {
  const seconds = Math.max(0, Math.floor(Number(value) || 0));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const remainder = seconds % 60;
  return hours > 0
    ? `${hours}:${pad(minutes)}:${pad(remainder)}`
    : `${pad(minutes)}:${pad(remainder)}`;
}

const TRANSCRIPT_TIMESTAMP_PATTERN = /\[\s*(?:\d{1,2}:)?\d{1,2}:\d{2}(?:[.,]\d{1,3})?\s*\]\s*/g;

export function stripVoiceJournalTimestamps(value) {
  return String(value || "")
    .replace(TRANSCRIPT_TIMESTAMP_PATTERN, "")
    .split("\n")
    .map((line) => line.replace(/[ \t]+/g, " ").trim())
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function appendSegmentText(current, next) {
  if (!current) return next;
  if (/^[,.;:!?…%)\]}]/.test(next) || /[(\[{„“]$/.test(current)) return `${current}${next}`;
  return `${current} ${next}`;
}

export function groupVoiceJournalSegments(segments) {
  const usableSegments = Array.isArray(segments)
    ? segments.filter((segment) => (
      segment
      && Number.isFinite(Number(segment.start))
      && String(segment.text || "").trim()
    ))
    : [];
  const grouped = [];
  let current = null;
  const flush = () => {
    if (current?.text) grouped.push(current);
    current = null;
  };
  usableSegments.forEach((segment) => {
    const start = Math.max(0, Number(segment.start));
    const rawEnd = Number(segment.end);
    const end = Number.isFinite(rawEnd) ? Math.max(start, rawEnd) : start;
    const text = String(segment.text || "").trim();
    const gap = current ? start - current.end : 0;
    if (current && gap >= 1.8) flush();
    if (!current) {
      current = { start, end, text };
    } else {
      current.text = appendSegmentText(current.text, text);
      current.end = Math.max(current.end, end);
    }
    const endsSentence = /[.!?…][\]”’"']?$/.test(current.text);
    const longEnoughWithoutPunctuation = current.text.length >= 280 || (
      current.end - current.start >= 18 && current.text.length >= 80
    );
    if (endsSentence || longEnoughWithoutPunctuation) flush();
  });
  flush();
  return grouped;
}

export function organizeVoiceJournalTranscript(segments, fallbackText = "") {
  const usableSegments = Array.isArray(segments)
    ? segments.filter((segment) => segment && String(segment.text || "").trim())
    : [];
  if (!usableSegments.length) return String(fallbackText || "").trim();
  const paragraphs = [];
  let paragraph = "";
  let previousEnd = null;
  usableSegments.forEach((segment) => {
    const text = String(segment.text || "").trim();
    const start = Number(segment.start);
    const pause = previousEnd === null || !Number.isFinite(start) ? 0 : start - previousEnd;
    const sentenceBoundary = /[.!?…][\]”’"']?$/.test(paragraph);
    if (paragraph && (pause >= 1.5 || (paragraph.length >= 500 && sentenceBoundary))) {
      paragraphs.push(paragraph);
      paragraph = text;
    } else {
      paragraph = `${paragraph} ${text}`.trim();
    }
    const end = Number(segment.end);
    previousEnd = Number.isFinite(end) ? end : start;
  });
  if (paragraph) paragraphs.push(paragraph);
  return paragraphs.join("\n\n");
}
