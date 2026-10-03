# Codex Instructions

- Read `PROJECT_MAP.md` first, then inspect only files relevant to the requested widget or feature.
- Follow `docs/GIT-WORKFLOW.md`: `main` is protected, `dev` is integration, and new AI tasks use `ai/<agent>/<task>` through `scripts/start-ai-task.ps1`. Checkpoint or stop on dirty work before switching. Use separate worktrees for parallel agents. The owner has explicitly authorized publishing completed, tested tasks to `main` and GitHub: finish, integrate into `dev`, then run `scripts/publish-main.ps1` from the clean main worktree. Honor any task-specific request to hold publication. Do not bypass main protection for other purposes.
- Do not modify or remove the Git backup scripts and `save-*` / `auto-*` tags unless the user explicitly asks.
- Keep changes minimal. Do not refactor app code or change behavior unless asked.
- Avoid generated/heavy context: `node_modules/`, `dist/`, `reports/`, `server.log`, `.tmp-*`, `covers/`, raw DBs, caches, and large data snapshots.
- For widget work, start from `index.html` `data-widget` markup, the matching `js/widget-*.js`, related helper/API/store files, and nearby CSS in `styles.css`.
- Preserve existing IDs, `data-widget` names, localStorage keys, API routes, and JSON schemas.
- Use `rg` for search. Run focused tests such as `npm run test:run -- tests/<file>.test.js` when touching tested logic.
