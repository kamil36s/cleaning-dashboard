const BASE_URL = "/api/timeline/activity";

async function readJson(response) {
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(payload.error || response.statusText || "Activity API error");
    error.code = payload.code || "api_error";
    throw error;
  }
  return payload;
}

export async function fetchTimelineActivity(options = {}, fetchImpl = fetch) {
  const query = new URLSearchParams();
  if (options.from) query.set("from", options.from);
  if (options.to) query.set("to", options.to);
  if (Array.isArray(options.sources)) query.set("sources", options.sources.join(","));
  if (options.journalContent) query.set("journalContent", options.journalContent);
  return readJson(await fetchImpl(`${BASE_URL}?${query}`, { cache: "no-store" }));
}

function fileToBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || "").split(",", 2)[1] || "");
    reader.onerror = () => reject(new Error("Could not read the selected file"));
    reader.readAsDataURL(file);
  });
}

export async function importLoopHabits(file, fetchImpl = fetch) {
  const contentBase64 = await fileToBase64(file);
  return readJson(await fetchImpl(`${BASE_URL}/habits/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name, contentBase64 }),
  }));
}

export async function importHowWeFeel(file, fetchImpl = fetch) {
  const contentBase64 = await fileToBase64(file);
  return readJson(await fetchImpl(`${BASE_URL}/emotions/import`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name, contentBase64 }),
  }));
}
