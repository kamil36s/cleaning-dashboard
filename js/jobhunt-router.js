const WORKSPACES = new Set([
  "home", "jobs", "tracks", "applications", "profile", "skills", "insights", "sources", "review", "advanced",
]);

const TRACK_TABS = new Set(["overview", "analytics", "jobs", "skills", "search", "policy"]);
const INSIGHT_TABS = new Set(["market", "sources", "applications", "tracks", "career", "experiments"]);
const REVIEW_FILTERS = new Set(["all", "job-data", "duplicates", "sources"]);

function cleanSegment(value) {
  try {
    return decodeURIComponent(String(value || "")).trim();
  } catch {
    return "";
  }
}

export function parseJobhuntHash(hash = "") {
  const raw = String(hash || "").replace(/^#/, "").replace(/^\/+|\/+$/g, "");
  const parts = raw.split("/").filter(Boolean).map(cleanSegment);
  if (!parts.length) return { workspace: "home", canonical: "home" };

  const [first, second, third] = parts;
  if (first === "job" && second) {
    return { workspace: "jobs", jobId: second, canonical: `jobs/${encodeURIComponent(second)}` };
  }
  if (first === "jobs") {
    return {
      workspace: "jobs",
      jobId: second || null,
      canonical: second ? `jobs/${encodeURIComponent(second)}` : "jobs",
    };
  }
  if (first === "track" && second) {
    const tab = TRACK_TABS.has(third) ? third : "overview";
    return {
      workspace: "tracks",
      trackId: second,
      trackTab: tab,
      canonical: `track/${encodeURIComponent(second)}/${tab}`,
    };
  }
  if (first === "tracks") return { workspace: "tracks", canonical: "tracks" };
  if (first === "insights") {
    const insightsTab = INSIGHT_TABS.has(second) ? second : "market";
    return {
      workspace: "insights",
      insightsTab,
      canonical: `insights/${insightsTab}`,
    };
  }
  if (first === "review") {
    const reviewFilter = REVIEW_FILTERS.has(second) ? second : "all";
    return {
      workspace: "review",
      reviewFilter,
      canonical: reviewFilter === "all" ? "review" : `review/${reviewFilter}`,
    };
  }
  if (first === "profile" && second === "assessments") {
    return { workspace: "profile", profileTab: "assessments", canonical: "profile/assessments" };
  }
  if (first === "advanced") {
    const advancedSection = second || "diagnostics";
    return {
      workspace: "advanced",
      advancedSection,
      canonical: advancedSection === "diagnostics" ? "advanced" : `advanced/${encodeURIComponent(advancedSection)}`,
    };
  }
  if (!WORKSPACES.has(first)) return { workspace: "home", canonical: "home", invalid: true };
  return { workspace: first, canonical: first };
}

export function jobhuntHref(route) {
  if (typeof route === "string") return `#${route.replace(/^#/, "")}`;
  if (route?.workspace === "jobs" && route.jobId) return `#jobs/${encodeURIComponent(route.jobId)}`;
  if (route?.workspace === "tracks" && route.trackId) {
    return `#track/${encodeURIComponent(route.trackId)}/${route.trackTab || "overview"}`;
  }
  if (route?.workspace === "review" && route.reviewFilter && route.reviewFilter !== "all") {
    return `#review/${route.reviewFilter}`;
  }
  return `#${route?.workspace || "home"}`;
}

export function createJobhuntRouter({ windowObject = globalThis.window, onChange = () => {} } = {}) {
  let started = false;
  const read = () => parseJobhuntHash(windowObject?.location?.hash || "");
  const emit = () => onChange(read());

  return {
    read,
    start() {
      if (started || !windowObject) return read();
      started = true;
      windowObject.addEventListener("hashchange", emit);
      const route = read();
      if (!windowObject.location.hash || route.invalid) {
        windowObject.history.replaceState(null, "", `${windowObject.location.pathname}${windowObject.location.search}#${route.canonical}`);
      }
      onChange(route);
      return route;
    },
    navigate(target, { replace = false } = {}) {
      const href = jobhuntHref(target);
      if (replace) {
        windowObject.history.replaceState(null, "", `${windowObject.location.pathname}${windowObject.location.search}${href}`);
        emit();
      } else if (windowObject.location.hash === href) {
        emit();
      } else {
        windowObject.location.hash = href.slice(1);
      }
    },
    destroy() {
      if (!started || !windowObject) return;
      windowObject.removeEventListener("hashchange", emit);
      started = false;
    },
  };
}
