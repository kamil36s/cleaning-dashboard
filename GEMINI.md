# Gemini Instructions — Cleaning Dashboard

This is a personal, data-bearing dashboard. Treat it as a production system even when it runs only on localhost.

## Mandatory preflight

1. Read `AGENTS.md` and `PROJECT_MAP.md` before inspecting or editing code.
2. Work directly on `main`. Do not create or switch branches unless the user explicitly asks.
3. Run `git status --short --branch` before editing. If Git reports an index, object, lock, or repository error, stop all Git writes and report the exact error. Never "repair" Git by deleting `.git/index`, `.git`, refs, tags, or user files.
4. Inspect only the requested feature's entry markup, matching `js/widget-*.js` or page controller, store/API helpers, nearby CSS, and focused tests.
5. Before changing persistent behavior, identify the current localStorage key, API route, file/SQLite store, and JSON schema.

## Non-negotiable safety rules

- Never delete, reset, truncate, reseed over, or replace user data to make a feature work.
- Never clear localStorage, a database, or `data/settings/*.json` outside an isolated test environment.
- Schema migrations must be additive and backward-compatible. Preserve unknown fields and buckets.
- Initialization must finish loading durable data before any seed or migration can save. A seed must be idempotent and must merge into loaded data, never race it.
- Preserve IDs, `data-widget` values, localStorage keys, API routes, JSON shapes, and existing records unless the user explicitly changes a contract.
- Do not modify Git backup scripts or `save-*` / `auto-*` tags unless explicitly requested.
- Do not use destructive Git commands (`reset --hard`, `clean -fd`, forced checkout, deleting the index) or overwrite unrelated working-tree changes.
- Do not run broad formatters or refactor fragile files such as `styles.css`, `index.html`, or `server.py` for a small widget task.
- Use `apply_patch` for surgical source edits. Keep the diff limited to the requested feature.

## To-do module contract

- Main dashboard markup: `index.html` with `data-widget="todo"`.
- Main widget controller: `js/widget-todo.js`.
- Full page: `todo.html` and `js/todo.js`.
- Shared persistence/model: `js/todo-store.js` and `/api/settings/todo` backed by `data/settings/todo.json`.
- Existing localStorage key: `todo-items-v1`.
- Buckets are distinct: `now`, `projects`, `ideas`, `shopping`.
- The main dashboard's active task list must render only `bucket === "now"`. Projects, ideas, and shopping items must not leak into it.
- Project-only fields (`description`, `priority`, `order`, `subtasks`) must not be added to ordinary tasks or shopping items.
- Hidden `ideas` data must remain stored even if the full To-do page does not render that section.
- Backlog seeding must run only after server/local hydration and must never duplicate, overwrite, or resurrect deliberately deleted seed projects.

## Verification before claiming success

- Run syntax/build validation and the focused tests for every touched feature.
- For To-do work, run at minimum:
  - `npm run test:run -- tests/todo-store.test.js tests/todo-page.test.js tests/widget-todo.test.js`
  - `npm run build`
- A static string-search test or HTTP 200 response does not prove the page works. Execute the browser module in a DOM test and assert rendered records/counts.
- Recheck the persistent data file after testing: record count by bucket and file hash must remain unchanged unless the user explicitly requested a data edit.
- Re-run `git status --short --branch` and inspect the final focused diff. Report tests honestly; do not claim manual browser verification unless it was actually performed.
