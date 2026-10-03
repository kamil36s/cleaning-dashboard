import path from "node:path";
import { pathToFileURL } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("habits app dashboard widget", () => {
  beforeEach(() => {
    const today = `${new Date().toISOString().slice(0, 10)}T00:00:00Z`;
    document.body.innerHTML = `
      <section id="habits-app-card">
        <div id="habits-app-root"></div>
      </section>
    `;
    localStorage.clear();
    vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
    window.HABIT_DB = {
      habits: [
        {
          id: 17,
          name: "Don't drink",
          type: 0,
          unit: "",
          points: [[Date.parse(today), 2]],
        },
        {
          id: 50,
          name: "Pregabalin",
          type: 1,
          unit: "mg",
          points: [[Date.parse(today), 150000]],
        },
      ],
    };
  });

  afterEach(() => vi.unstubAllGlobals());

  it("renders both Loop entry types and queues binary edits locally", async () => {
    const moduleUrl = pathToFileURL(path.resolve("js/widget-habits-app.js")).href;
    await import(`${moduleUrl}?test=${Date.now()}`);

    expect(document.querySelectorAll(".habits-app-habit")).toHaveLength(2);
    expect(document.querySelector(".habits-app-entry.is-numeric.is-complete span")?.textContent).toBe("150");
    expect(document.querySelectorAll(".habits-app-manage-row")).toHaveLength(2);
    expect(document.querySelectorAll(".habits-app-heatmap-day")).toHaveLength(7);
    expect(document.querySelectorAll(".habits-app-heatmap-day-cell")).toHaveLength(84);
    [...document.querySelectorAll(".habits-app-habit")]
      .find((button) => button.textContent.includes("Pregabalin"))
      ?.click();
    expect(document.querySelectorAll(".habits-app-period-stats .habits-app-metrics > div")).toHaveLength(4);
    expect(document.querySelector(".habits-app-period-stats")?.textContent).toContain("Średnia");
    expect(document.querySelector(".habits-app-period-stats")?.textContent).toContain("150 mg");
    expect(document.querySelector(".habits-app-period-stats")?.textContent).toContain("od początku trackowania");
    expect(document.querySelector(".habits-app-period-stats")?.textContent).toContain("skuteczność 100%");
    expect(document.querySelector("[aria-label='Nowsze 12 tygodni historii']")?.disabled).toBe(true);
    expect(document.querySelector(".habits-app-heatmap-day-cell")?.title).toMatch(/2026/);
    const newestFirstDay = document.querySelector(".habits-app-heatmap-day-cell")?.title;
    document.querySelector("[aria-label='Starsze 12 tygodni historii']")?.click();
    expect(document.querySelector(".habits-app-heatmap-day-cell")?.title).not.toBe(newestFirstDay);
    expect(document.querySelector("[aria-label='Nowsze 12 tygodni historii']")?.disabled).toBe(false);
    expect(document.getElementById("habits-app-card")?.dataset.ready).toBe("true");
    const visibleDays = [...document.querySelectorAll(".habits-app-date-head strong")];
    expect(visibleDays.at(-1)?.textContent).toBe(String(new Date().getUTCDate()));

    document.querySelector(".habits-app-entry.is-binary")?.click();

    expect(document.getElementById("habits-app-pending")?.textContent).toContain("1 zmiana");
    expect(JSON.parse(localStorage.getItem("habits.app.preview-mutations.v1"))).toHaveLength(1);
  });

  it("hides archived habits from the board but keeps them in management", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({
        cursor: "20",
        habits: [
          { id: "active", name: "Meditation", type: "BINARY", category: "HABIT", position: 0, archived: false, revision: 2 },
          { id: "hidden", name: "Squats", type: "NUMERIC", category: "HABIT", position: 1, archived: true, revision: 2 },
        ],
        entries: [],
      }),
    })));
    const moduleUrl = pathToFileURL(path.resolve("js/widget-habits-app.js")).href;
    await import(`${moduleUrl}?archived=${Date.now()}`);

    await vi.waitFor(() => expect(document.querySelectorAll(".habits-app-habit")).toHaveLength(1));
    expect(document.querySelector(".habits-app-habit strong")?.textContent).toBe("Meditation");
    expect(document.querySelectorAll(".habits-app-manage-row")).toHaveLength(2);
    expect(document.querySelectorAll(".habits-app-manage-row input:checked")).toHaveLength(1);
  });

  it("drags a habit into a new order and persists positions through sync", async () => {
    let apiHabits = [
      { id: "creatine", name: "Creatine", type: "NUMERIC", category: "SUPPLEMENT", position: 0, archived: false, revision: 2 },
      { id: "concerta", name: "Concerta/Atenza", type: "NUMERIC", category: "MEDICATION", position: 1, archived: false, revision: 2 },
      { id: "b-complex", name: "Biotyna/B complex", type: "BINARY", category: "SUPPLEMENT", position: 2, archived: false, revision: 2 },
    ];
    const fetchMock = vi.fn(async (url, options = {}) => {
      if (url === "/api/habits/sync") {
        const request = JSON.parse(options.body);
        const positions = new Map(request.mutations.map((mutation) => [mutation.entityId, mutation.payload.position]));
        apiHabits = apiHabits.map((habit) => positions.has(habit.id)
          ? { ...habit, position: positions.get(habit.id), revision: habit.revision + 1 }
          : habit);
        return {
          ok: true,
          json: async () => ({
            acknowledgedMutationIds: request.mutations.map((mutation) => mutation.mutationId),
            changes: [],
            conflicts: [],
          }),
        };
      }
      return { ok: true, json: async () => ({ cursor: "40", habits: apiHabits, entries: [] }) };
    });
    vi.stubGlobal("fetch", fetchMock);
    const moduleUrl = pathToFileURL(path.resolve("js/widget-habits-app.js")).href;
    await import(`${moduleUrl}?reorder=${Date.now()}`);
    await vi.waitFor(() => expect(document.querySelectorAll(".habits-app-habit")).toHaveLength(3));

    const habitButtons = [...document.querySelectorAll(".habits-app-habit")];
    const creatine = habitButtons.find((button) => button.textContent.includes("Creatine"));
    const bComplex = habitButtons.find((button) => button.textContent.includes("Vitamin B Complex"));
    const transfer = { effectAllowed: "", dropEffect: "", setData: vi.fn(), getData: () => "creatine" };
    const dragStart = new Event("dragstart", { bubbles: true, cancelable: true });
    Object.defineProperty(dragStart, "dataTransfer", { value: transfer });
    creatine.dispatchEvent(dragStart);
    const drop = new Event("drop", { bubbles: true, cancelable: true });
    Object.defineProperties(drop, { dataTransfer: { value: transfer }, clientY: { value: 0 } });
    bComplex.dispatchEvent(drop);

    await vi.waitFor(() => {
      const names = [...document.querySelectorAll(".habits-app-habit strong")].map((node) => node.textContent);
      expect(names).toEqual(["Concerta/Atenza", "Creatine", "Vitamin B Complex"]);
    });
    const syncRequest = JSON.parse(fetchMock.mock.calls.find(([url]) => url === "/api/habits/sync")[1].body);
    expect(syncRequest.mutations.map((mutation) => mutation.payload.position)).toEqual([0, 1]);
  });

  it("publishes fresh API habits for dependent dashboard widgets", async () => {
    const today = new Date().toISOString().slice(0, 10);
    const updateListener = vi.fn();
    document.addEventListener("habits-app:data-updated", updateListener, { once: true });
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({
        cursor: "31",
        habits: [{ id: "drink", name: "Don't drink", type: "BINARY", category: "HABIT", position: 0, archived: false, revision: 2 }],
        entries: [{ id: `drink:${today}`, habitId: "drink", date: today, status: "DONE", valueMilli: null, revision: 1 }],
      }),
    })));

    const moduleUrl = pathToFileURL(path.resolve("js/widget-habits-app.js")).href;
    await import(`${moduleUrl}?live=${Date.now()}`);

    await vi.waitFor(() => expect(updateListener).toHaveBeenCalledOnce());
    expect(window.HABITS_APP_LIVE_DATA.cursor).toBe("31");
    expect(window.HABITS_APP_LIVE_DATA.habits[0].entries.get(today)).toBe(2);
  });

  it("adds a supplement from the toolbar and shows it after server confirmation", async () => {
    let apiHabits = [];
    const fetchMock = vi.fn(async (url, options = {}) => {
      if (url === "/api/habits/sync") {
        const request = JSON.parse(options.body);
        const mutation = request.mutations[0];
        apiHabits = [{ id: mutation.entityId, ...mutation.payload, revision: 1, archived: false }];
        return { ok: true, json: async () => ({ acknowledgedMutationIds: [mutation.mutationId], conflicts: [], changes: [] }) };
      }
      return { ok: true, json: async () => ({ cursor: "40", habits: apiHabits, entries: [] }) };
    });
    vi.stubGlobal("fetch", fetchMock);
    const moduleUrl = pathToFileURL(path.resolve("js/widget-habits-app.js")).href;
    await import(`${moduleUrl}?add=${Date.now()}`);
    await vi.waitFor(() => expect(document.querySelectorAll(".habits-app-habit")).toHaveLength(0));

    document.getElementById("habits-app-add").click();
    expect(document.getElementById("habits-app-add-dialog").open).toBe(true);
    expect([...document.querySelectorAll("#habits-app-add-category option")].map((option) => option.textContent)).toEqual(["Nawyk", "Lek", "Suplement"]);
    document.getElementById("habits-app-add-name").value = "Witamina B12";
    document.getElementById("habits-app-add-category").value = "SUPPLEMENT";
    const type = document.getElementById("habits-app-add-type");
    type.value = "NUMERIC";
    type.dispatchEvent(new Event("change"));
    expect(document.getElementById("habits-app-add-numeric").hidden).toBe(false);
    document.getElementById("habits-app-add-unit").value = "mg";
    document.getElementById("habits-app-add-target").value = "5";
    document.getElementById("habits-app-add-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    await vi.waitFor(() => expect(document.querySelector(".habits-app-habit strong")?.textContent).toBe("Witamina B12"));
    expect(document.getElementById("habits-app-add-dialog").open).toBe(false);
    expect(document.querySelector(".habits-app-habit small")?.textContent).toContain("Suplement");
    const request = JSON.parse(fetchMock.mock.calls.find(([url]) => url === "/api/habits/sync")[1].body);
    expect(request.mutations[0].payload).toMatchObject({ category: "SUPPLEMENT", type: "NUMERIC", unit: "mg", targetValueMilli: 5000 });
  });

  it("keeps the add form open with an error when the server rejects the new habit", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url) => url === "/api/habits/sync"
      ? { ok: false, status: 503, json: async () => ({ error: "Serwer niedostępny" }) }
      : { ok: true, json: async () => ({ cursor: "40", habits: [], entries: [] }) }));
    const moduleUrl = pathToFileURL(path.resolve("js/widget-habits-app.js")).href;
    await import(`${moduleUrl}?add-error=${Date.now()}`);
    await vi.waitFor(() => expect(document.querySelectorAll(".habits-app-habit")).toHaveLength(0));

    document.getElementById("habits-app-add").click();
    document.getElementById("habits-app-add-name").value = "Spacer";
    document.getElementById("habits-app-add-form").dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

    await vi.waitFor(() => expect(document.getElementById("habits-app-add-error")?.textContent).toBe("Serwer niedostępny"));
    expect(document.getElementById("habits-app-add-dialog").open).toBe(true);
    expect(document.querySelectorAll(".habits-app-habit")).toHaveLength(0);
  });

  it("renders configured reminder bells and never requests notification permission on load", async () => {
    class NotificationMock {
      static permission = "default";
      static requestPermission = vi.fn(async () => "granted");
    }
    vi.stubGlobal("Notification", NotificationMock);
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({
        cursor: "50",
        habits: [{
          id: "vitamin-d", name: "Vitamin D", type: "BINARY", category: "SUPPLEMENT",
          position: 0, archived: false, revision: 2,
          reminderConfig: {
            enabled: true, scheduleType: "daily", selectedWeekdays: [], intervalDays: 2,
            intervalAnchorDate: null, timeGroupIds: ["morning"], customTimes: [], snoozeMinutes: 10,
            skipIfCompleted: true, completionPolicy: "day",
          },
        }],
        entries: [],
        reminderTimeGroups: [{ id: "morning", name: "Morning", localTime: "09:00", sortOrder: 0 }],
        reminderSettings: { browserNotificationsEnabled: false },
        reminderStates: [],
      }),
    })));
    const moduleUrl = pathToFileURL(path.resolve("js/widget-habits-app.js")).href;
    await import(`${moduleUrl}?reminders=${Date.now()}`);
    await vi.waitFor(() => expect(document.querySelector(".habits-app-row-bell")).toBeTruthy());

    expect(document.querySelector(".habits-app-row-bell")?.title).toContain("Morning 09:00");
    expect(NotificationMock.requestPermission).not.toHaveBeenCalled();
    document.getElementById("habits-app-reminders")?.click();
    expect(document.getElementById("habits-reminder-panel")?.textContent).toContain("Vitamin D");
  });
});
