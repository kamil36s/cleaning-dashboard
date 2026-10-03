const API_ORIGINS = ["", "http://127.0.0.1:8000", "http://localhost:8000"];

export class EventsApiError extends Error {
  constructor(message, details = {}) {
    super(message);
    this.name = "EventsApiError";
    this.details = details;
    this.google = details.google || null;
    this.status = details.status || null;
    this.source = details.source || null;
  }
}

export async function fetchDashboardEvents(options = {}) {
  try {
    const apiPayload = await tryFetchApiEvents(options);
    if (apiPayload) return apiPayload;
  } catch (error) {
    if (options.requireGoogle) throw error;
  }

  if (options.requireGoogle) {
    throw new EventsApiError("Google Calendar API is unavailable", {
      source: "dashboard_api",
    });
  }

  throw new EventsApiError("Events API is unavailable", {
    source: "dashboard_api",
  });
}

export async function syncGoogleCalendarNow(options = {}) {
  const response = await fetchApi("/api/google-calendar/sync", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ force: Boolean(options.force) }),
  });
  if (!response.ok) {
    throw new Error(`google_calendar_sync_${response.status}`);
  }
  return response.json();
}

export async function upsertGoogleCalendarEvent(event) {
  const response = await fetchApi("/api/events/google/upsert", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event }),
  });
  if (!response.ok) {
    const payload = await readErrorPayload(response);
    throw new Error(payload?.error || `google_calendar_upsert_${response.status}`);
  }
  return response.json();
}

export async function saveEventDashboardOverride(event) {
  const response = await fetchApi("/api/events/override", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event }),
  });
  if (!response.ok) {
    const payload = await readErrorPayload(response);
    throw new Error(payload?.error || `events_override_${response.status}`);
  }
  return response.json();
}

export async function saveLocalDashboardEvent(event) {
  const response = await fetchApi("/api/events/local/upsert", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event }),
  });
  if (!response.ok) {
    const payload = await readErrorPayload(response);
    throw new Error(payload?.error || `events_local_upsert_${response.status}`);
  }
  return response.json();
}

export async function saveEventCountdownCategory(label, id = "") {
  const response = await fetchApi("/api/events/categories", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(id ? { id, label } : { label }),
  });
  if (!response.ok) {
    const payload = await readErrorPayload(response);
    throw new Error(payload?.error || `events_category_save_${response.status}`);
  }
  return response.json();
}

export async function uploadEventCountdownCover(event, dataUrl) {
  const response = await fetchApi("/api/events/countdown-cover", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event, dataUrl }),
  });
  if (!response.ok) {
    const payload = await readErrorPayload(response);
    throw new Error(payload?.error || `events_countdown_cover_${response.status}`);
  }
  return response.json();
}

export async function deleteEventCountdownCover(event) {
  const response = await fetchApi("/api/events/countdown-cover", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ event, remove: true }),
  });
  if (!response.ok) {
    const payload = await readErrorPayload(response);
    throw new Error(payload?.error || `events_countdown_cover_delete_${response.status}`);
  }
  return response.json();
}

export async function deleteGoogleCalendarEvent(event) {
  const response = await fetchApi("/api/events/google/delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      external: event?.external,
      calendarId: event?.external?.calendarId,
      eventId: event?.external?.eventId,
    }),
  });
  if (!response.ok) {
    const payload = await readErrorPayload(response);
    throw new Error(payload?.error || `google_calendar_delete_${response.status}`);
  }
  return response.json();
}

export async function fetchGoogleCalendars(options = {}) {
  const params = new URLSearchParams({
    refresh: options.refresh ? "1" : "0",
  });
  return fetchApiJson(`/api/google-calendar/calendars?${params.toString()}`);
}

async function tryFetchApiEvents(options = {}) {
  const params = new URLSearchParams({
    sync: options.sync === false ? "0" : "1",
    past: options.showPastEvents ? "1" : "0",
    local: options.includeLocal === false ? "0" : "1",
    google: options.includeGoogle === false ? "0" : "1",
  });
  if (Number.isFinite(options.windowDays) && options.windowDays > 0) {
    params.set("days", String(Math.ceil(options.windowDays)));
  }
  const payload = await fetchApiJson(`/api/events?${params.toString()}`);
  if (payload && Array.isArray(payload.events)) {
    const google = payload.google || {};
    if (options.requireGoogle) {
      if (!google.configured) {
        throw new EventsApiError("Google Calendar is not configured", {
          google,
          source: "dashboard_api",
        });
      }
      if (!google.connected) {
        throw new EventsApiError("Google Calendar is not connected", {
          google,
          source: "dashboard_api",
        });
      }
      if (google.syncError) {
        throw new EventsApiError(`Google Calendar sync failed: ${google.syncError}`, {
          google,
          source: "dashboard_api",
        });
      }
    }
    return {
      events: payload.events,
      countdownCategories: Array.isArray(payload.countdownCategories) ? payload.countdownCategories : [],
      countdownCategoryCovers: payload.countdownCategoryCovers && typeof payload.countdownCategoryCovers === "object"
        ? payload.countdownCategoryCovers
        : {},
      google,
      source: "dashboard_api",
    };
  }
  return null;
}

async function fetchApiJson(path, options = {}) {
  let lastError = null;

  for (const origin of API_ORIGINS) {
    try {
      const response = await fetch(`${origin}${path}`, { cache: "no-store", ...options });
      if (!response.ok) {
        const payload = await readErrorPayload(response);
        lastError = new EventsApiError(payload?.error || `api_fetch_${response.status}`, {
          status: response.status,
          payload,
          source: origin || "same-origin",
        });
        continue;
      }

      const contentType = response.headers?.get?.("content-type") || "";
      if (contentType && !contentType.toLowerCase().includes("application/json")) {
        lastError = new Error("api_fetch_non_json");
        continue;
      }

      return await response.json();
    } catch (error) {
      lastError = error;
    }
  }

  throw lastError || new Error("api_unavailable");
}

async function fetchApi(path, options = {}) {
  let lastResponse = null;
  let lastError = null;

  for (const origin of API_ORIGINS) {
    try {
      const response = await fetch(`${origin}${path}`, { cache: "no-store", ...options });
      if (response.ok) return response;
      lastResponse = response;
    } catch (error) {
      lastError = error;
    }
  }

  if (lastResponse) return lastResponse;
  throw lastError || new Error("api_unavailable");
}

async function readErrorPayload(response) {
  try {
    return await response.json();
  } catch (error) {
    return null;
  }
}
