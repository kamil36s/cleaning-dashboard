#!/usr/bin/env python3
"""Import Mi Fitness TCX files or a ZIP archive into Live Workout history."""

import argparse
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from live_workout_store import LiveWorkoutStore
from live_workout_tcx import read_tcx_source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="A .tcx file or ZIP containing TCX files")
    parser.add_argument(
        "--db",
        type=Path,
        default=ROOT / "data" / "live-workout.sqlite",
        help="Live Workout SQLite database",
    )
    parser.add_argument(
        "--mi-fitness-timezone",
        default="Europe/Warsaw",
        help="Timezone for Mi Fitness activity IDs that are incorrectly marked with Z",
    )
    args = parser.parse_args()
    if not args.source.exists():
        parser.error(f"source does not exist: {args.source}")

    store = LiveWorkoutStore(args.db)
    imported = read_tcx_source(args.source, mi_fitness_timezone=args.mi_fitness_timezone)
    for workout in imported:
        saved = store.import_summary(workout)
        sample_note = f"{saved.get('sample_count', 0)} HR samples"
        print(
            f"{saved['id']}: {saved['import_file']} | "
            f"{saved['duration_seconds']} s | {saved['avg_hr']} avg BPM | {sample_note}"
        )
    print(f"Imported {len(imported)} workout(s) into {args.db}")


if __name__ == "__main__":
    main()
