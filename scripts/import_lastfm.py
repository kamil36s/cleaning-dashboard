from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lastfm_store import LASTFM_STORE


def main():
    parser = argparse.ArgumentParser(description="Import a Last.fm recent-tracks CSV into the dashboard database.")
    parser.add_argument("csv", type=Path, help="Path to a CSV with uts, artist, album and track columns")
    args = parser.parse_args()
    print(json.dumps(LASTFM_STORE.import_csv(args.csv), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
