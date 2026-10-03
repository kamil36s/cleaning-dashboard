# Git Auto-Versioning / AI-safe development

Canonical helpers are the existing `scripts/save.ps1`, `restore.ps1`,
`autosave.ps1`, `history.ps1` plus the task/status/worktree helpers beside them.
Requires Git and Windows PowerShell 5.1 (tested with Git 2.27.0.windows.1).
All ordinary operations work offline. No service or Windows startup task is installed.

## NORMAL WORKFLOW

1. Inspect: `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/version-status.ps1`
2. Save existing work: `.\scripts\save.ps1`. On protected `main`, a deliberate
   initial/emergency save requires `.\scripts\save.ps1 -AllowMain`.
3. Start: `.\scripts\start-ai-task.ps1 -Agent codex -Task "dashboard-sync-api"`.
   Dirty files cause a refusal. `dev` is created from `main` only when first needed;
   existing `dev` is preserved. Names become lowercase safe ASCII slugs. Duplicate
   task branches are rejected. Optional `-Sync` fetches origin and fast-forwards
   dev from origin/dev; missing remote/dev or divergence stops with an error.
4. Work on `ai/codex/dashboard-sync-api`.
5. Save during work: `.\scripts\save.ps1`.
6. Finish/review: `.\scripts\finish-ai-task.ps1`. This checkpoints dirty work and
   reports commits/files/stat relative to the merge base with dev. No default merge.
7. Review and run relevant application tests.
8. Integrate: `.\scripts\finish-ai-task.ps1 -Merge`. Only merges into `dev`;
   conflicts remain unresolved for review (`git status`; resolve or `git merge --abort`).
   The AI branch is retained.
9. After testing dev, publish from the clean main worktree:

```powershell
.\scripts\publish-main.ps1
```

The owner has authorized this final step for completed, tested tasks. The helper
fetches origin, verifies that local and remote main are aligned, checks that dev
descends from main and does not reconnect the archived credential-bearing history,
merges dev, scans the published tree for credential patterns, creates an annotated
release tag, and atomically pushes both `main` and the repository's current default
branch `master` plus the tag. It stops on conflicts or remote changes without a
force push. Honor an explicit request to hold publication.

## Checkpoint and numbering

`save.ps1` takes a repository-wide lock shared by linked worktrees, checks for
conflicts/unfinished operations, rejects detached HEAD, stages `git add -A`,
generates a changelog, commits, and creates an annotated `build-XXXX` tag.
It uses max numeric build tag + 1 across all branches/worktrees, including tags
not reachable from HEAD. Existing `save-*` / `auto-*` tags remain valid and untouched.
The old `-Prefix save|auto` argument is accepted for compatibility; new saves always
use build tags. A clean tree prints `No changes to checkpoint.` and creates nothing.

`CHANGELOG-AUTO.md` records Added, Modified, Deleted, Renamed, files changed,
insertions, deletions and binary count using the staged Git diff, without an LLM.
Stats describe staged input **before adding the new generated entry**; any user's
existing changelog edit is part of that input. The entry is committed with the
files, so a second call does not generate another build. Binary files have no
line counts. Git-quoted unusual filenames remain unambiguous.

On pre-commit failure the old index and changelog are restored; source edits stay.
On tag failure the commit is retained and the error prints the exact tag repair
command. Do not make another checkpoint until that missing tag is repaired.
A forced process kill can leave staged files/an unfinished changelog; inspect
`git status` and `git log -1` before retrying. No command rewrites history.

The lock coordinates these helpers, not arbitrary Git/IDE operations. Do not run
other index writers in the same worktree during checkpoint. Parallel agents must
use separate worktrees. Do not delete the lock file: the open file handle owns
the lock; an idle file on disk is normal and releases on process exit/crash.

## IF AI BREAKS THE PROJECT

```powershell
.\scripts\save.ps1
.\scripts\restore.ps1 -Build build-0001
```

Save the broken work first (on main use `-AllowMain`). Restore refuses dirty files,
validates the tag, creates `recovery/build-0001` (or a numbered suffix), and checks
out the tagged commit. The original branch, commits, tags, untracked changes and
ignored-file collisions are protected; there is no reset/clean. Run from an idle
working directory and stop processes writing tracked files before changing versions.

Return with `git switch <original-branch>`; if recovery edits exist, checkpoint them
first. `git switch main` returns to the baseline branch when that was your starting
point. Old tags work too: `.\scripts\restore.ps1 -Tag save-20261002-221435`.
**Historical versions contain historical scripts**: pre-baseline restore helpers
were destructive. After inspecting an old tag, use `git switch main` to return;
do not invoke the old restore script from that historical checkout.

Git restores source code. Ignored SQLite databases, local settings, `.env`, media
and private archives are not backed up/restored by a build tag. A code rollback
can require a compatible database backup after a schema migration. Keep separate
application/data backups and an independent off-machine copy for disk failure.
This baseline verifies Git safety, not every dashboard feature or migration.

## Main protection and installation

This repository has `core.hooksPath=.githooks` configured locally. On a fresh clone:

```powershell
git config core.hooksPath .githooks
```

`pre-commit` blocks direct main commits; `pre-merge-commit` also guards merge
commits. `save.ps1` independently rejects dirty main unless `-AllowMain` or the
explicit environment override is present. Overrides are restored/removed after
use; never set them globally for everyday development. Hooks are local accident
protection, not access control: `--no-verify`, plumbing and fast-forward operations
can bypass hooks. Keep promotion deliberate; server protection is independent.

Optional GitHub configuration: in repository Settings ? Branches / Rulesets,
protect `main`, require reviewed pull requests and passing relevant checks, block
force pushes and deletion, and decide who may bypass. No remote settings were
changed here. See [GitHub's branch protection instructions](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/managing-a-branch-protection-rule) for current UI/options and plan availability.

## Worktrees for parallel agents

```powershell
.\scripts\start-ai-worktree.ps1 -Agent astra -Task dashboard-sync-api -Path ..\dashboard-astra-sync
```

Creates a new sibling directory and unique `ai/astra/dashboard-sync-api` branch
from dev, leaving the primary branch unchanged. Duplicate branches and existing
paths are refused. Use absolute paths when not invoking from the repository root.
Run the helpers inside that worktree. Dependencies and ignored configuration/data
are not copied; install dependencies separately and allocate separate ports and
private databases before running multiple app instances. Never point two agents
at the same working directory. Build numbering/lock and hooks are shared.
Review `git worktree list`; remove a finished clean worktree with
`git worktree remove <path>` only after preserving/merging its work. Branches are
not automatically deleted.

## Watcher and push

`.\scripts\autosave.ps1 -Minutes 20` runs visibly in the foreground, checks once
per interval and checkpoints only actual changes. Ctrl+C stops it. `-Once` performs
one check (used by tests). Legacy `-IntervalSeconds` is supported; `-QuietSeconds`
is accepted but no longer controls debounce. Watcher has no main override and stops
on an error/conflict. `npm run dev` now starts only Vite, so development does not
silently create commits. Start `npm run autosave` separately when desired.

No default network call or push during a checkpoint. `.\scripts\save.ps1 -Push` explicitly pushes
only the current branch and newly created tag atomically to origin, establishing
upstream if needed. It never pushes all historical tags or force-pushes. If no new
checkpoint exists, `-Push` pushes only the branch; push an older tag explicitly if
needed. Missing remote or failed push reports an error but preserves local work.

`npm run save`, `npm run history`, `npm run restore -- build-0001`,
`npm run git:status` and `npm run git:checkpoint` are shortcuts; PowerShell remains
canonical. Test without touching the real repo: `npm run git:test`.

## Exactly five everyday commands

```powershell
.\scripts\version-status.ps1
.\scripts\save.ps1
.\scripts\start-ai-task.ps1 -Agent codex -Task "task-name"
.\scripts\finish-ai-task.ps1
.\scripts\restore.ps1 -Build build-0001
```
