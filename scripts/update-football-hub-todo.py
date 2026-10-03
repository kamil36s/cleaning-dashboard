"""Apply the reviewed Football Hub acceptance results without changing other projects.

Dry-run by default. Runtime Todo is private, ignored data, not part of a Git commit.
"""
import argparse
import copy
import json
import os
from pathlib import Path
import time


def update(data, now):
    result = copy.deepcopy(data)
    projects = [p for p in result if p.get("id") == "football-hub" and p.get("bucket") == "projects"]
    if len(projects) != 1 or len(projects[0].get("subtasks", [])) != 21:
        raise ValueError("Expected the existing Football Hub project with exactly 21 subtasks")
    project = projects[0]
    expected = {f"football-hub-st-{i}" for i in range(1, 23) if i != 21}
    if {s["id"] for s in project["subtasks"]} != expected:
        raise ValueError("Subtask IDs changed; review the project before updating")
    for task in project["subtasks"]:
        task["done"] = task["id"] not in {"football-hub-st-10", "football-hub-st-11"}
        task["updatedAt"] = now
        if not task["done"]:
            previous = task.get("description", "").split("\n[Football Hub audit]")[0]
            task["description"] = previous + "\n[Football Hub audit] PARTIAL: widok i adapter gotowe; brak skonfigurowanego API-Football. Nie potwierdzono danych produkcyjnych."
    project["done"] = False
    project["completedAt"] = None
    project["updatedAt"] = now
    previous = project.get("description", "").split("\n[Football Hub audit]")[0]
    project["description"] = previous + "\n[Football Hub audit] 2026-10-03: 19/21 zweryfikowane w ai/astra/football-hub (osobny worktree, bez merge). Kod czeka na integrację. Pozostały Coaches i Transfers — brak dostępu API-Football. Szczegóły: docs/FOOTBALL-HUB.md."
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("todo", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    target = args.todo.resolve(strict=True)
    for attempt in range(5):
        original = target.read_bytes()
        data = json.loads(original.decode("utf-8-sig"))
        result = update(data, int(time.time() * 1000))
        if not args.apply:
            print("Dry run: Football Hub 19/21; 21 existing IDs preserved; other projects unchanged.")
            return
        temporary = target.with_name(target.name + ".football-hub.tmp")
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        if target.read_bytes() != original:
            temporary.unlink()
            continue
        backup = target.with_name(f"todo.football-hub-before-{time.time_ns()}.json.bak")
        backup.write_bytes(original)
        if target.read_bytes() != original:
            temporary.unlink()
            continue
        os.replace(temporary, target)
        saved = json.loads(target.read_text(encoding="utf-8"))
        before_other = [p for p in data if p.get("id") != "football-hub"]
        after_other = [p for p in saved if p.get("id") != "football-hub"]
        if before_other != after_other:
            raise RuntimeError("Concurrent update detected after write; review the saved backup before any further changes")
        print(f"Updated Football Hub: 19/21. Other {len(before_other)} items unchanged. Backup: {backup.name}")
        return
    raise RuntimeError("Todo is changing concurrently; no update applied")


if __name__ == "__main__":
    main()
