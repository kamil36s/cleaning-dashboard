import { beforeEach, describe, expect, it } from "vitest";
import {
  addMovingChecklistTask,
  getDefaultMovingChecklistState,
  getMovingChecklistView,
  loadMovingChecklistState,
  saveMovingChecklistState,
  toggleMovingChecklistTask,
  updateMovingChecklistTask,
  updateMovingChecklistUi,
} from "../js/moving-checklist-store.js";

describe("moving checklist store", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("loads editable sample moving data when storage is empty", () => {
    const state = loadMovingChecklistState();

    expect(state.sections.length).toBeGreaterThan(3);
    expect(state.sections[0].title).toBe("Before moving");
    expect(state.sections.some((section) => section.title === "Moving day")).toBe(true);
  });

  it("persists changes and keeps them after reload", () => {
    const state = getDefaultMovingChecklistState();
    const updated = updateMovingChecklistTask(state, "moving-task-bank", {
      title: "Change address in bank and insurance",
      notes: "Do both on the same admin day.",
      dueDate: "2026-04-16",
    });

    saveMovingChecklistState(updated);
    const reloaded = loadMovingChecklistState();
    const adminSection = reloaded.sections.find((section) => section.id === "moving-section-admin");
    const task = adminSection.tasks.find((item) => item.id === "moving-task-bank");

    expect(task.title).toBe("Change address in bank and insurance");
    expect(task.notes).toContain("admin day");
    expect(task.dueDate).toBe("2026-04-16");
  });

  it("cascades completion state to nested subtasks", () => {
    const state = getDefaultMovingChecklistState();
    const updated = toggleMovingChecklistTask(state, "moving-task-meter-readings", true);
    const movingDay = updated.sections.find((section) => section.id === "moving-section-day");
    const task = movingDay.tasks.find((item) => item.id === "moving-task-meter-readings");

    expect(task.completed).toBe(true);
    expect(task.subtasks.every((subtask) => subtask.completed)).toBe(true);
  });

  it("can move a top-level task between sections", () => {
    const state = getDefaultMovingChecklistState();
    const updated = updateMovingChecklistTask(state, "moving-task-bank", {
      sectionId: "moving-section-before",
    });

    const beforeSection = updated.sections.find((section) => section.id === "moving-section-before");
    const adminSection = updated.sections.find((section) => section.id === "moving-section-admin");

    expect(beforeSection.tasks.some((task) => task.id === "moving-task-bank")).toBe(true);
    expect(adminSection.tasks.some((task) => task.id === "moving-task-bank")).toBe(false);
  });

  it("keeps parent context visible when filters match only nested subtasks", () => {
    const state = getDefaultMovingChecklistState();
    const beforeSection = state.sections.find((section) => section.id === "moving-section-before");
    beforeSection.tasks[0].priority = "low";
    beforeSection.tasks[0].subtasks[1].priority = "high";

    const filteredState = updateMovingChecklistUi(state, {
      priorityFilter: "high",
      statusFilter: "all",
    });
    const view = getMovingChecklistView(filteredState);
    const rentalTask = view.sections
      .flatMap((section) => section.tasks)
      .find((task) => task.id === "moving-task-rental");

    expect(rentalTask).toBeTruthy();
    expect(rentalTask.selfMatches).toBe(false);
    expect(rentalTask.subtasks.some((task) => task.id === "moving-task-rental-proof")).toBe(true);
  });

  it("counts parent tasks with subtasks as containers in progress stats", () => {
    let state = getDefaultMovingChecklistState();
    state = addMovingChecklistTask(state, {
      title: "Container task",
      sectionId: "moving-section-before",
      completed: false,
      priority: "high",
      dueDate: "2026-04-30",
    });
    const parent = state.sections
      .find((section) => section.id === "moving-section-before")
      .tasks.find((task) => task.title === "Container task");

    state = addMovingChecklistTask(state, {
      title: "Finished child",
      parentTaskId: parent.id,
      completed: true,
    });
    state = addMovingChecklistTask(state, {
      title: "Remaining child",
      parentTaskId: parent.id,
      completed: false,
    });

    const view = getMovingChecklistView(state);

    expect(view.stats.overall.total).toBe(29);
    expect(view.stats.overall.completed).toBe(3);
    expect(view.stats.overall.open).toBe(26);
    expect(view.stats.overall.highPriorityOpen).toBe(10);
  });

  it("keeps progress totals consistent with open and completed counts", () => {
    let state = {
      sections: [
        {
          id: "section",
          title: "Section",
          collapsed: false,
          tasks: [
            {
              id: "parent",
              title: "Parent",
              completed: true,
              priority: "medium",
              dueDate: "",
              notes: "",
              collapsed: false,
              subtasks: [],
            },
          ],
        },
      ],
      ui: {
        statusFilter: "all",
        priorityFilter: "all",
        sortBy: "manual",
        quickAddSectionId: "section",
      },
    };

    for (let index = 0; index < 12; index += 1) {
      state = addMovingChecklistTask(state, {
        title: `Done child ${index + 1}`,
        parentTaskId: "parent",
        completed: true,
      });
    }
    for (let index = 0; index < 2; index += 1) {
      state = addMovingChecklistTask(state, {
        title: `Open child ${index + 1}`,
        parentTaskId: "parent",
        completed: false,
      });
    }

    const view = getMovingChecklistView(state);

    expect(view.stats.overall.completed).toBe(13);
    expect(view.stats.overall.open).toBe(2);
    expect(view.stats.overall.total).toBe(15);
    expect(view.stats.overall.total).toBe(view.stats.overall.completed + view.stats.overall.open);
    expect(view.stats.sections[0].total).toBe(view.stats.sections[0].completed + view.stats.sections[0].open);
  });

  it("summarizes the filtered visible task set", () => {
    const state = {
      sections: [
        {
          id: "section",
          title: "Section",
          collapsed: false,
          tasks: [
            {
              id: "visible-open-1",
              title: "Visible open 1",
              completed: false,
              priority: "medium",
              dueDate: "",
              notes: "",
              collapsed: false,
              subtasks: [],
            },
            {
              id: "visible-open-2",
              title: "Visible open 2",
              completed: false,
              priority: "medium",
              dueDate: "",
              notes: "",
              collapsed: false,
              subtasks: [],
            },
            {
              id: "hidden-open",
              title: "Hidden open",
              completed: false,
              priority: "high",
              dueDate: "",
              notes: "",
              collapsed: false,
              subtasks: [],
            },
            {
              id: "visible-done",
              title: "Visible done",
              completed: true,
              priority: "medium",
              dueDate: "",
              notes: "",
              collapsed: false,
              subtasks: [],
            },
          ],
        },
      ],
      ui: {
        statusFilter: "all",
        priorityFilter: "medium",
        sortBy: "manual",
        quickAddSectionId: "section",
      },
    };

    const view = getMovingChecklistView(state);

    expect(view.sections[0].tasks.map((task) => task.id)).toEqual([
      "visible-open-1",
      "visible-open-2",
      "visible-done",
    ]);
    expect(view.stats.overall.open).toBe(2);
    expect(view.stats.overall.completed).toBe(1);
    expect(view.stats.overall.total).toBe(3);
  });
});
