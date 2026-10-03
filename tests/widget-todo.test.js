import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

function item(id, title, bucket) {
  return {
    id,
    title,
    bucket,
    due: null,
    done: false,
    completedAt: null,
    createdAt: 1,
    updatedAt: 1,
  };
}

describe("main dashboard To-do widget", () => {
  beforeEach(() => {
    vi.resetModules();
    window.happyDOM.setURL("http://localhost:3000/cleaning-dashboard/");
    localStorage.clear();
    localStorage.setItem("todo-items-v1", JSON.stringify([
      item("task", "Visible task", "now"),
      item("project", "Hidden project", "projects"),
      item("idea", "Hidden idea", "ideas"),
      item("shopping", "Visible shopping", "shopping"),
    ]));
    document.body.innerHTML = `
      <section class="card todo" data-widget="todo">
        <form id="todo-quick-form">
          <input id="todo-quick-input" class="todo-input">
          <input id="todo-quick-date" class="todo-date-input">
        </form>
        <span id="todo-quick-count"></span>
        <ul id="todo-quick-list"></ul>
        <div id="todo-quick-empty"></div>
        <form id="todo-shopping-form">
          <input id="todo-shopping-input" class="todo-input">
          <input id="todo-shopping-date" class="todo-date-input">
        </form>
        <span id="todo-shopping-count"></span>
        <ul id="todo-shopping-list"></ul>
        <div id="todo-shopping-empty"></div>
        <div id="todo-summary"></div>
        <a id="todo-more"></a>
        <button id="todo-toggle-done" type="button"></button>
      </section>`;
  });

  afterEach(() => {
    vi.restoreAllMocks();
    localStorage.clear();
    document.body.replaceChildren();
  });

  it("shows only the now bucket in active tasks", async () => {
    await import("../js/widget-todo.js");

    const taskList = document.getElementById("todo-quick-list");
    const shoppingList = document.getElementById("todo-shopping-list");
    expect(taskList.textContent).toContain("Visible task");
    expect(taskList.textContent).not.toContain("Hidden project");
    expect(taskList.textContent).not.toContain("Hidden idea");
    expect(document.getElementById("todo-quick-count").textContent).toBe("1");
    expect(shoppingList.textContent).toContain("Visible shopping");
  });
});
