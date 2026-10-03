import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

describe("To-do page layout and backlog integration", () => {
  const page = readFileSync(resolve(process.cwd(), "todo.html"), "utf8");
  const script = readFileSync(resolve(process.cwd(), "js/todo.js"), "utf8");
  const styles = readFileSync(resolve(process.cwd(), "styles.css"), "utf8");
  const bodyMarkup = page.match(/<body[^>]*>([\s\S]*?)<script\s+type="module"/)?.[1] || "";

  beforeEach(() => {
    vi.resetModules();
    window.happyDOM.setURL("http://localhost:3000/cleaning-dashboard/todo.html");
    localStorage.clear();
    document.body.className = "page-todo";
    document.body.innerHTML = bodyMarkup;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    localStorage.clear();
    document.body.replaceChildren();
  });

  it("removes 'Pomysły' from view without affecting other columns", () => {
    expect(page).not.toContain('data-bucket="ideas"');
    expect(page).not.toContain('Luźne rzeczy do rozkminy');
  });

  it("organizes the layout into two rows: top row for Taski and Shopping, bottom for Projekty", () => {
    expect(page).toContain('class="todo-layout"');
    expect(page).toContain('class="todo-top-row"');
    expect(page).toContain('class="todo-projects-section"');

    // Both Taski and Shopping list are in the page
    expect(page).toContain('data-bucket="now"');
    expect(page).toContain('data-bucket="shopping"');
    expect(page).toContain('data-bucket="projects"');

    // Top row contains taski and shopping
    const topRowIndex = page.indexOf('class="todo-top-row"');
    const projectsIndex = page.indexOf('class="todo-projects-section"');
    expect(topRowIndex).toBeGreaterThan(-1);
    expect(projectsIndex).toBeGreaterThan(topRowIndex);

    const nowIndex = page.indexOf('data-bucket="now"');
    const shoppingIndex = page.indexOf('data-bucket="shopping"');
    expect(nowIndex).toBeGreaterThan(topRowIndex);
    expect(nowIndex).toBeLessThan(projectsIndex);
    expect(shoppingIndex).toBeGreaterThan(topRowIndex);
    expect(shoppingIndex).toBeLessThan(projectsIndex);
  });

  it("provides proper styling with 16-24px gap and responsive stacking", () => {
    expect(styles).toContain(".todo-layout");
    expect(styles).toContain("gap: 20px;");
    expect(styles).toContain(".todo-top-row");
    expect(styles).toContain("grid-template-columns: repeat(2, minmax(0, 1fr));");
    expect(styles).toContain(".todo-projects-section");
    expect(styles).toContain(".todo-priority-badge.p0");
    expect(styles).toContain(".todo-priority-badge.p4");
    expect(styles).toContain(".todo-project-progress-bar");
    expect(styles).toContain(".todo-subtask-item");
  });

  it("seeds backlog and supports project card expand/collapse, subtasks and priorities", () => {
    expect(script).toContain("ensureBacklogSeeded");
    expect(script).toContain("expandedProjectIds");
    expect(script).toContain("renderProjectCard");
    expect(script).toContain("renderEditProjectCard");
    expect(script).toContain("PRIORITY_LABELS");
    expect(script).toContain("toggleSubtask");
    expect(script).toContain("addSubtask");
    expect(script).toContain("deleteSubtask");
  });

  it("executes the page controller and renders persisted tasks, shopping items, and projects", async () => {
    localStorage.setItem("todo-items-v1", JSON.stringify([
      {
        id: "task-1",
        title: "Persisted task",
        bucket: "now",
        due: null,
        done: false,
        completedAt: null,
        createdAt: 1,
        updatedAt: 1,
      },
      {
        id: "shopping-1",
        title: "Persisted shopping item",
        bucket: "shopping",
        due: null,
        done: false,
        completedAt: null,
        createdAt: 2,
        updatedAt: 2,
      },
    ]));

    await import("../js/todo.js");

    await vi.waitFor(() => {
      expect(document.querySelector('[data-bucket="now"] .todo-list').textContent)
        .toContain("Persisted task");
      expect(document.querySelector('[data-bucket="shopping"] .todo-list').textContent)
        .toContain("Persisted shopping item");
      expect(document.getElementById("todo-projects-count").textContent).toBe("20");
    });
  });

  it("waits for server hydration before seeding and never saves a projects-only snapshot", async () => {
    window.happyDOM.setURL("http://localhost:5173/cleaning-dashboard/todo.html");
    const serverItems = [
      {
        id: "server-task",
        title: "Server task",
        bucket: "now",
        due: null,
        done: false,
        completedAt: null,
        createdAt: 1,
        updatedAt: 1,
      },
      {
        id: "server-shopping",
        title: "Server shopping",
        bucket: "shopping",
        due: null,
        done: false,
        completedAt: null,
        createdAt: 2,
        updatedAt: 2,
      },
    ];
    const savedPayloads = [];
    let resolveServerRead;
    const serverRead = new Promise((resolveRead) => {
      resolveServerRead = resolveRead;
    });

    vi.stubGlobal("fetch", vi.fn(async (_url, options = {}) => {
      if (options.method === "POST") {
        const payload = JSON.parse(options.body);
        savedPayloads.push(payload.data);
        return {
          ok: true,
          json: async () => ({ ok: true, data: payload.data }),
        };
      }
      return serverRead;
    }));

    await import("../js/todo.js");
    await Promise.resolve();
    expect(savedPayloads).toHaveLength(0);

    resolveServerRead({
      ok: true,
      json: async () => ({ ok: true, data: serverItems }),
    });

    await vi.waitFor(() => {
      expect(document.querySelector('[data-bucket="now"] .todo-list').textContent)
        .toContain("Server task");
      expect(document.querySelector('[data-bucket="shopping"] .todo-list').textContent)
        .toContain("Server shopping");
      expect(savedPayloads).toHaveLength(1);
    });

    expect(savedPayloads[0]).toHaveLength(22);
    expect(savedPayloads[0].some((item) => item.id === "server-task")).toBe(true);
    expect(savedPayloads[0].some((item) => item.id === "server-shopping")).toBe(true);
  });
});
