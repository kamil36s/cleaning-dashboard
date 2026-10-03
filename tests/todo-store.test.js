import path from "node:path";
import { pathToFileURL } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

async function importFreshModule() {
  const modulePath = pathToFileURL(path.resolve("js/todo-store.js")).href;
  return import(`${modulePath}?t=${Date.now()}-${Math.random()}`);
}

describe("todo store completion visibility", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-05-20T10:00:00+02:00"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps completed tasks visible in active lists for 3 days", async () => {
    const {
      addTodo,
      isTodoActiveListVisible,
      listTodos,
      toggleTodo,
    } = await importFreshModule();

    const item = addTodo({ title: "Zrobic rzecz", due: "19/05/2026", bucket: "now" });
    const completed = toggleTodo(item.id, true);

    expect(completed.done).toBe(true);
    expect(isTodoActiveListVisible(completed)).toBe(true);

    vi.setSystemTime(new Date("2026-05-23T09:59:00+02:00"));
    expect(isTodoActiveListVisible(listTodos()[0])).toBe(true);

    vi.setSystemTime(new Date("2026-05-23T10:01:00+02:00"));
    expect(isTodoActiveListVisible(listTodos()[0])).toBe(false);
  });

  it("archives old completed tasks and clears completedAt when reopened", async () => {
    const {
      isTodoActiveListVisible,
      isTodoArchived,
      listTodos,
      toggleTodo,
    } = await importFreshModule();

    localStorage.setItem("todo-items-v1", JSON.stringify([{
      id: "old-done",
      title: "Stary completed",
      bucket: "now",
      due: "2026-05-10",
      done: true,
      completedAt: new Date("2026-05-15T10:00:00+02:00").getTime(),
      createdAt: new Date("2026-05-10T10:00:00+02:00").getTime(),
      updatedAt: new Date("2026-05-15T10:00:00+02:00").getTime(),
    }]));

    const archived = listTodos()[0];
    expect(isTodoArchived(archived)).toBe(true);
    expect(isTodoActiveListVisible(archived)).toBe(false);

    const reopened = toggleTodo("old-done", false);
    expect(reopened.done).toBe(false);
    expect(reopened.completedAt).toBe(null);
    expect(isTodoActiveListVisible(reopened)).toBe(true);
  });
});

describe("projects and subtasks management", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("keeps tasks and shopping simple, but supports priority, description, and subtasks for projects", async () => {
    const { addTodo, listTodos } = await importFreshModule();

    const task = addTodo({ title: "Zadanie zwykle", bucket: "now" });
    const shopping = addTodo({ title: "Chleb", bucket: "shopping" });
    const project = addTodo({
      title: "Nowy projekt",
      bucket: "projects",
      priority: "P1",
      description: "Opis projektu",
    });

    expect(task.description).toBeUndefined();
    expect(task.priority).toBeUndefined();
    expect(task.subtasks).toBeUndefined();

    expect(shopping.description).toBeUndefined();
    expect(shopping.priority).toBeUndefined();
    expect(shopping.subtasks).toBeUndefined();

    expect(project.description).toBe("Opis projektu");
    expect(project.priority).toBe("P1");
    expect(Array.isArray(project.subtasks)).toBe(true);
    expect(project.subtasks.length).toBe(0);
  });

  it("handles adding, toggling, updating and deleting subtasks", async () => {
    const {
      addTodo,
      addSubtask,
      toggleSubtask,
      updateSubtask,
      deleteSubtask,
      listTodos,
    } = await importFreshModule();

    const project = addTodo({
      title: "Projekt z subtaskami",
      bucket: "projects",
      priority: "P0",
    });

    const subtask1 = addSubtask(project.id, { title: "Pierwszy krok", description: "Detale" });
    const subtask2 = addSubtask(project.id, { title: "Drugi krok" });

    expect(subtask1.title).toBe("Pierwszy krok");
    expect(subtask1.description).toBe("Detale");
    expect(subtask1.done).toBe(false);

    let updatedProject = listTodos().find((p) => p.id === project.id);
    expect(updatedProject.subtasks.length).toBe(2);
    expect(updatedProject.done).toBe(false);

    // Toggle 1st subtask -> project still not done
    toggleSubtask(project.id, subtask1.id, true);
    updatedProject = listTodos().find((p) => p.id === project.id);
    expect(updatedProject.done).toBe(false);

    // Toggle 2nd subtask -> all done -> project becomes done: true
    toggleSubtask(project.id, subtask2.id, true);
    updatedProject = listTodos().find((p) => p.id === project.id);
    expect(updatedProject.done).toBe(true);

    // Untoggle 1st subtask -> project becomes done: false again
    toggleSubtask(project.id, subtask1.id, false);
    updatedProject = listTodos().find((p) => p.id === project.id);
    expect(updatedProject.done).toBe(false);

    // Update subtask
    updateSubtask(project.id, subtask1.id, { title: "Zmieniony tytul", description: "Nowy opis" });
    updatedProject = listTodos().find((p) => p.id === project.id);
    expect(updatedProject.subtasks[0].title).toBe("Zmieniony tytul");
    expect(updatedProject.subtasks[0].description).toBe("Nowy opis");

    // Delete subtask
    deleteSubtask(project.id, subtask1.id);
    updatedProject = listTodos().find((p) => p.id === project.id);
    expect(updatedProject.subtasks.length).toBe(1);
    // Since only subtask2 remains and it was done: true, project is now done: true
    expect(updatedProject.done).toBe(true);
  });

  it("seeds 20 backlog projects idempotently and respects deletedSeedProjectIds", async () => {
    const {
      ensureBacklogSeeded,
      listTodos,
      deleteTodo,
      getDeletedSeedProjectIds,
      sortProjects,
    } = await importFreshModule();

    expect(listTodos().length).toBe(0);

    const addedFirst = ensureBacklogSeeded();
    expect(addedFirst).toBe(true);

    const itemsAfterSeed = listTodos();
    expect(itemsAfterSeed.length).toBe(20);

    // Idempotent: second call should not add any duplicates
    const addedSecond = ensureBacklogSeeded();
    expect(addedSecond).toBe(false);
    expect(listTodos().length).toBe(20);

    // Check sorting
    const sorted = sortProjects(itemsAfterSeed);
    expect(sorted[0].priority).toBe("P0");
    expect(sorted[0].id).toBe("git-auto-versioning");
    expect(sorted[1].priority).toBe("P0");
    expect(sorted[1].id).toBe("dashboard-sync-api");

    // Check that Project 1 has completed subtask 1 and 3 as expected
    const p1 = itemsAfterSeed.find((p) => p.id === "git-auto-versioning");
    expect(p1.subtasks.find((st) => st.order === 1).done).toBe(true);
    expect(p1.subtasks.find((st) => st.order === 3).done).toBe(true);
    expect(p1.subtasks.find((st) => st.order === 2).done).toBe(false);

    // Delete a seeded project
    const deleteSuccess = deleteTodo("git-auto-versioning");
    expect(deleteSuccess).toBe(true);
    expect(listTodos().length).toBe(19);

    const deletedIds = getDeletedSeedProjectIds();
    expect(deletedIds.has("git-auto-versioning")).toBe(true);

    // Now re-run seed: git-auto-versioning must NOT come back!
    ensureBacklogSeeded();
    expect(listTodos().length).toBe(19);
    expect(listTodos().some((p) => p.id === "git-auto-versioning")).toBe(false);
  });

  it("does not resurrect a completed seeded project removed by clear done", async () => {
    const {
      clearDone,
      ensureBacklogSeeded,
      getDeletedSeedProjectIds,
      listTodos,
      toggleTodo,
    } = await importFreshModule();

    ensureBacklogSeeded();
    toggleTodo("git-auto-versioning", true);
    expect(listTodos().find((item) => item.id === "git-auto-versioning").done).toBe(true);

    clearDone();
    expect(listTodos().some((item) => item.id === "git-auto-versioning")).toBe(false);
    expect(getDeletedSeedProjectIds().has("git-auto-versioning")).toBe(true);

    ensureBacklogSeeded();
    expect(listTodos().some((item) => item.id === "git-auto-versioning")).toBe(false);
  });
});
