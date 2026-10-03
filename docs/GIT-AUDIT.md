# Git audit and acceptance report ? 2026-10-02

## CURRENT REPOSITORY STATE

- Current branch: `main` throughout implementation; no task/test branches created
  in the user's repository. `master` and `origin/master` retained.
- Initial HEAD: `294c192` (`backup: save-20260902-191648`).
- Initial working tree: **dirty**, 132 modified paths and 1,086 untracked files.
  These were pre-existing dashboard development, documentation, assets, tests,
  private archive outputs and database backup copies; not changes from this task.
- Initial tags: `save-20260902-191527`, `save-20260902-191648`; no build tags.
- Origin retained: `https://github.com/kamil36s/cleaning-dashboard.git`.
  No fetch/push/network Git operation was run against this origin.
- Hooks initially unconfigured; `.githooks` and `.gitattributes` absent.
- Existing helpers: `scripts/save.ps1`, `restore.ps1`, `autosave.ps1`, `history.ps1`;
  npm aliases save/restore/history/autosave. `npm run dev` implicitly launched
  autosave. No other Git versioning implementation was found in relevant scripts/docs.
- Preservation commit: `4ec89f7`, tag **`save-20261002-221435`**, made with the
  original save helper before changing that implementation. Source working tree
  was clean immediately afterward. It retains all prior eligible work.
- Final Git system baseline: **`build-0001`** (annotated tag; resolve with
  `git rev-parse build-0001^{commit}`). The final checkpoint contains this report.
- Hooks now configured locally as `core.hooksPath=.githooks`; LF shell hooks are
  repository-managed. Future clones must configure hooks explicitly.
- `dev` and task branches are created on demand, not as unused empty branches.
- `git fsck --connectivity-only --no-dangling` passes. Existing historical tags,
  commits and remote configuration were preserved.

## Feature audit: BEFORE and AFTER

PASS means executed/verified, not just a discovered file. Initial statuses describe
this repository before implementation; the audit itself was performed this session.

| Feature | BEFORE | AFTER | Existing implementation | Problems | Required action / result |
|---------|--------|-------|-------------------------|----------|--------------------------|
| 1. Repository audit | PASS | PASS | Git history/status/refs/config inspected | 1,218 dirty entries; unchecked private outputs | Preserved source snapshot; reviewed excludes and history integrity |
| 2. Branch model | PARTIAL | PASS | main, master, origin/master | No integration/task workflow; instructions required main | Lazy dev from main, sanitized task branches; updated agent instructions; tests 6, 7, 12 |
| 3. Checkpoint | PASS | PASS | save.ps1; original helper actually saved pre-existing work | Main-only; no new workflow metadata | Extended existing helper; tests 1?5, 8, 14, 17 |
| 4. Build numbering | MISSING | PASS | Timestamp save/auto tags only | No build-* source of truth | Global max numeric tag + 1, common lock; tests 5, 12, 22, 23 |
| 5. Changelog without AI | MISSING | PASS | None | No technical change record | Staged diff categories/numstat, same-commit log; tests 2?4, 13, 14 |
| 6. Start AI task | MISSING | PASS | None | No safe task isolation helper | Dirty refusal, dev base, slug validation, explicit sync; tests 6, 10, 25 |
| 7. Finish AI task | MISSING | PASS | None | No review/optional integration flow | Checkpoint + dev diff, explicit dev-only merge, stop on conflicts; tests 7, 15 |
| 8. Safe restore | BROKEN | PASS | restore.ps1 | reset --hard + clean -fd destroyed unsaved work | Recovery branch, dirty refusal and ignored collision guard; tests 9, 10, 16, 21 |
| 9. Main protection | MISSING | PASS | No hooks | Main was only accepted development branch | pre-commit, pre-merge-commit and helper guard, scoped override; tests 8, 24 |
| 10. Workflow documentation | MISSING | PASS | npm aliases only | No complete practical workflow | GIT-WORKFLOW.md; all executable workflow steps covered by integration tests |
| 11. Optional watcher | PARTIAL | PASS | autosave.ps1 (30 s + quiet window) | Coupled to npm dev/main; no dedicated verified interval contract | Visible, opt-in interval loop, clean no-op, Ctrl+C; test 11 |
| 12. Worktrees / parallel agents | MISSING | PASS | Git capability only | No helper/isolation instructions; old lock per working Git dir | Separate branches/directories, common lock/numbering; tests 12, 20, 22, 23 |

Version-status is also implemented and verified (test 18): current branch,
repository-wide latest build, HEAD/tag, dirty path count, ahead of dev, origin,
and hook configuration. Latest global build is explicitly distinct from HEAD.

## Safety and scope decisions

- Improved the existing helpers, without a parallel checkpoint implementation.
- Kept main checkout for this authorized repair/baseline, using `-AllowMain` only
  for the final checkpoint. Future ordinary development uses dev/AI branches.
- Corrected ignore rules for actual discovered SQLite backup copies (including
  a 2.6 GB live-workout copy), private normalized History Wiki exports/phase
  checkpoints, disposable Kermit index, and Todo Pocket build caches. No files
  were deleted. Already ignored `.env*`, databases/WAL/SHM, dependencies/builds,
  logs, local settings and raw archives remain ignored. No tracked ignored files
  were found. A bounded credential-pattern scan reported no matching candidates.
- Checkpoints reject likely secret/key/database paths, files over 50 MB and common
  credential signatures in staged content. This is a heuristic guard, not a proof
  that arbitrary source content contains no secrets. No secret values are logged.
- `git add -A` intentionally snapshots all nonignored work in that worktree, even
  pre-staged changes. Pre-commit failure restores the previous index and log.
- No `reset --hard`, `clean -fd`, force push, tag deletion or branch deletion.
- Local hooks prevent accidents, not deliberate bypasses; fast-forward updates
  do not execute commit hooks. GitHub protections remain optional and unchanged.
- Ignored runtime databases/settings/media are outside Git backup coverage.
  Source restore does not migrate or roll back databases. This is a verified
  source-code baseline, not certification of every existing dashboard feature.
- Runtime services updated tracked `data/kitchen-team-crests.json` during this
  session. That change was not authored here; the final snapshot preserves it.
  A running service may dirty that file again after the checkpoint.

## Files

Created:

- `.gitattributes`; `.githooks/pre-commit`; `.githooks/pre-merge-commit`.
- `scripts/git-common.ps1` (shared implementation/lock).
- `scripts/start-ai-task.ps1`; `scripts/finish-ai-task.ps1`.
- `scripts/start-ai-worktree.ps1`; `scripts/version-status.ps1`.
- `tests/test_git_workflow.py`.
- `docs/GIT-AUDIT.md`; `docs/GIT-WORKFLOW.md`; `CHANGELOG-AUTO.md` (generated).

Modified by this task:

- `scripts/save.ps1`, `restore.ps1`, `autosave.ps1`, `history.ps1`.
- `package.json`: remove implicit autosave from dev; add status/checkpoint/test aliases.
- `.gitignore` (included in the preservation commit).
- `AGENTS.md`, `PROJECT_MAP.md`: match the protected-main/task workflow.
- Local `.git/config`: hooksPath only; origin unchanged.
- Ignored canonical `data/settings/todo.json`: only project `git-auto-versioning`,
  all 12 subtasks completed with current timestamps and audit/baseline note.
  Updated through existing settings API; reread verifies all other 78 entries
  unchanged. Pre-update exact file backup:
  `data/backups/git-auto-versioning/todo-before-20261002-223317.json`.
  Refresh the Todo page to load authoritative server state. No Todo app/seed/schema
  changes, no other backlog project started.

## Controlled test results

Command: `python -m unittest discover -s tests -p test_git_workflow.py -v`.
Result: **25/25 PASS**, 69.034 seconds, Windows PowerShell 5.1 and Git 2.27.0.windows.1.
Every test creates disposable repositories outside the real repo, performs real
Git operations, and removes its own fixtures. Test origin is a local bare repo;
the user's GitHub origin is never contacted. Watcher test processes are stopped.

| Test | Verified result |
|------|-----------------|
| 1 | Clean checkpoint leaves HEAD/tags unchanged |
| 2 | Modified file ? commit/tag/changelog; repeat creates no loop |
| 3 | Added filename with spaces classified correctly |
| 4 | Deleted tracked file classified correctly |
| 5 | Sequential builds increase by one; max numeric tag is source of truth |
| 6 | Task name sanitized, AI branch based on dev; main unchanged |
| 7 | Finish reports correct ahead/diff, default no merge, explicit dev merge |
| 8 | Main raw commit/helper blocked; explicit override succeeds |
| 9 | Recovery recreates old content; original task history retained; repeat names safe |
| 10 | Dirty start/restore/worktree refuse and retain unsaved content |
| 11 | Watcher clean check makes no commit; real interval saves once, then stays idle |
| 12 | Worktree has independent branch/content and shared global numbering |
| 13 | Rename, binary, Unicode and mixed staged/unstaged input preserved |
| 14 | Failed commit restores exact prior index/log; retry has one entry |
| 15 | Merge conflict remains unresolved; checkpoint refuses conflicted index |
| 16 | Legacy save tag works; missing/malformed targets refused |
| 17 | Ignored secrets/DBs stay excluded; credential-like staged content refused |
| 18 | Status reports active hooks/no origin; history command runs |
| 19 | Missing remote fails only push after local success; explicit atomic push sets upstream and sends only new tag |
| 20 | Nested worktree and dirty detached checkpoint refused |
| 21 | Restore refuses overwriting an ignored local collision |
| 22 | Busy common lock refuses a second helper; after release checkpoint succeeds |
| 23 | Simultaneous worktree saves/retry create distinct build-0001/build-0002, retaining each agent's content |
| 24 | Main merge-commit hook blocks; deliberate scoped override succeeds |
| 25 | Explicit sync fails without origin; succeeds with local origin/dev |

Additional checks: repository connectivity, diff whitespace, local hook setup,
old-tag retention and canonical Todo readback. No dashboard rebuild or broad app
suite: application behavior was not changed. A whole-app stability guarantee is
outside this Git-system verification.

## Acceptance and everyday use

All 12 backlog capabilities are verified. Watcher is implemented but not started
for the user. Worktrees are available but no idle worktree/agent was created.
The final normal flow is `main ? dev ? ai/<agent>/<task> ? reviewed dev ? tested main`.
Checkpoint, numbering, changelog, restore, hook overrides, worktrees and exactly
five everyday commands are documented in [GIT-WORKFLOW.md](GIT-WORKFLOW.md).

**SAFE BASELINE BUILD: `build-0001`.**
