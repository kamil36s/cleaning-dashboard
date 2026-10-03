const escapeXml = (value) => String(value ?? "")
  .replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;")
  .replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;")
  .replaceAll("'", "&apos;");

const isoTime = (value) => new Date(Number(value)).toISOString();

export function exportWorkoutToTCX(session = {}) {
  const startedAt = Number(session.started_at || Date.now());
  const samples = Array.isArray(session.samples) ? session.samples : [];
  const duration = Math.max(0, Number(session.duration_seconds || 0));
  const calories = Math.max(0, Math.round(Number(session.active_calories || 0)));
  const trackpoints = samples.map((sample) => `
            <Trackpoint>
              <Time>${escapeXml(isoTime(sample.timestamp))}</Time>
              <HeartRateBpm><Value>${Math.round(Number(sample.heart_rate || 0))}</Value></HeartRateBpm>
            </Trackpoint>`).join("");
  return `<?xml version="1.0" encoding="UTF-8"?>
<TrainingCenterDatabase xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2">
  <Activities>
    <Activity Sport="Biking">
      <Id>${escapeXml(isoTime(startedAt))}</Id>
      <Lap StartTime="${escapeXml(isoTime(startedAt))}">
        <TotalTimeSeconds>${duration.toFixed(3)}</TotalTimeSeconds>
        <DistanceMeters>0</DistanceMeters>
        <Calories>${calories}</Calories>
        <Intensity>Active</Intensity>
        <TriggerMethod>Manual</TriggerMethod>
        <Track>${trackpoints}
        </Track>
      </Lap>
      <Notes>${escapeXml(session.title || "Indoor cycling")}</Notes>
    </Activity>
  </Activities>
</TrainingCenterDatabase>`;
}

export function downloadTextFile(filename, content, mimeType = "application/octet-stream") {
  const url = URL.createObjectURL(new Blob([content], { type: mimeType }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function collectLocalStorage(storage = window.localStorage) {
  const entries = {};
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (key != null) entries[key] = storage.getItem(key);
  }
  return entries;
}

export function validateFullBackup(data) {
  if (!data || data.kind !== "cleaning-dashboard-full-backup" || data.schemaVersion !== 1) {
    throw new Error("Nieobsługiwany format backupu");
  }
  if (!data.localStorage || typeof data.localStorage !== "object" || !Array.isArray(data.workouts)) {
    throw new Error("Backup nie zawiera wymaganych sekcji");
  }
  return data;
}

export function importLocalStorageBackup(data, { merge = true, storage = window.localStorage } = {}) {
  const backup = validateFullBackup(data);
  if (!merge) storage.clear();
  Object.entries(backup.localStorage).forEach(([key, value]) => {
    if (typeof key === "string" && typeof value === "string") storage.setItem(key, value);
  });
  return Object.keys(backup.localStorage).length;
}
