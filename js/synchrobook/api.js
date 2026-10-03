const API_ROOT = "/api/synchrobook";

async function request(path, options = {}) {
  const response = await fetch(`${API_ROOT}${path}`, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Synchrobook request failed (${response.status})`);
  return payload;
}

export const listBooks = () => request("/books");
export const getBook = (bookId) => request(`/books/${encodeURIComponent(bookId)}`);
export const getAlignment = (bookId) => request(`/books/${encodeURIComponent(bookId)}/alignment`);
export const getReport = (bookId) => request(`/books/${encodeURIComponent(bookId)}/report`);
export const getJob = (jobId) => request(`/jobs/${encodeURIComponent(jobId)}`);
export const listJobs = () => request("/jobs?limit=30");
export const getProcessingSettings = () => request("/processing-settings");
export const saveProcessingSettings = (highMemory) => request("/processing-settings", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ highMemory }),
});
export const resumeJob = (jobId, priority = 0) => request(`/jobs/${encodeURIComponent(jobId)}/resume`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ priority }),
});
export const deleteBook = (bookId) => request(`/books/${encodeURIComponent(bookId)}?confirm=delete`, { method: "DELETE" });

export function saveProgress(bookId, progress, { keepalive = false } = {}) {
  return request(`/books/${encodeURIComponent(bookId)}/progress`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(progress),
    keepalive,
  });
}

export const rebuildAlignment = (bookId) => request(`/books/${encodeURIComponent(bookId)}/rebuild-alignment`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
export const retranscribeAudio = (bookId) => request(`/books/${encodeURIComponent(bookId)}/retranscribe`, { method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" });
export const getReadingGuide = (bookId) => request(`/books/${encodeURIComponent(bookId)}/reading-guide`);
export const readingGuideAction = (bookId, action, data = {}) => request(`/books/${encodeURIComponent(bookId)}/reading-guide`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ action, data }),
});

export function importBook(formData, onProgress = () => {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_ROOT}/import`);
    xhr.responseType = "json";
    xhr.upload.addEventListener("progress", (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    });
    xhr.addEventListener("load", () => {
      const payload = xhr.response || {};
      if (xhr.status >= 200 && xhr.status < 300) resolve(payload);
      else reject(new Error(payload.error || `Import failed (${xhr.status})`));
    });
    xhr.addEventListener("error", () => reject(new Error("Could not reach the Synchrobook backend")));
    xhr.send(formData);
  });
}
