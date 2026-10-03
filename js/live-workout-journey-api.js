import { liveWorkoutRuntimeUrl } from "./live-workout-runtime-api.js";

const JOURNEY_URL = liveWorkoutRuntimeUrl("journey/santiago");
const POSTCARDS_URL = liveWorkoutRuntimeUrl("journey/postcards");
const MAX_POSTCARD_BYTES = 12 * 1024 * 1024;
const POSTCARD_TYPES = new Set(["image/jpeg", "image/png", "image/webp"]);

async function responseJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || payload.detail || `HTTP ${response.status}`);
  return payload;
}

export async function fetchJourneySnapshot({ includeCheckpoints = false } = {}) {
  const suffix = includeCheckpoints ? "?checkpoints=1" : "";
  return responseJson(await fetch(`${JOURNEY_URL}${suffix}`, { cache: "no-store" }));
}

export async function fetchJourneyPostcards() {
  const payload = await responseJson(await fetch(POSTCARDS_URL, { cache: "no-store" }));
  return payload.postcards || [];
}

export function journeyPostcardImageUrl(checkpointId, version = "") {
  const url = liveWorkoutRuntimeUrl(`journey/postcards/${encodeURIComponent(checkpointId)}/image`);
  return version ? `${url}?v=${encodeURIComponent(version)}` : url;
}

function fileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(String(reader.result || "").split(",", 2)[1] || ""), { once: true });
    reader.addEventListener("error", () => reject(new Error("Nie udało się odczytać pliku")), { once: true });
    reader.readAsDataURL(file);
  });
}

export async function uploadJourneyPostcard(checkpointId, file) {
  if (!POSTCARD_TYPES.has(file?.type)) throw new Error("Wybierz obraz JPEG, PNG albo WebP");
  if (!file.size || file.size > MAX_POSTCARD_BYTES) throw new Error("Pocztówka może mieć maksymalnie 12 MB");
  const payload = await responseJson(await fetch(POSTCARDS_URL, {
    method: "POST",
    // The runtime parses JSON without requiring a Content-Type header. Keeping
    // this a simple request avoids a cross-origin preflight before large uploads.
    body: JSON.stringify({
      checkpointId,
      filename: file.name,
      mimeType: file.type,
      dataBase64: await fileAsBase64(file),
    }),
  }));
  return payload.postcard;
}

export { JOURNEY_URL, POSTCARDS_URL, MAX_POSTCARD_BYTES };
