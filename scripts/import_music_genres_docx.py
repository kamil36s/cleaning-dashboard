"""Import a Word hierarchy of RYM genres into the canonical Music database."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from music_importers import parse_rym_genre_docx  # noqa: E402
from music_store import MusicStore  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("docx", type=Path)
    args = parser.parse_args()
    parsed = parse_rym_genre_docx(args.docx)
    result = MusicStore(ROOT).sync_genre_hierarchy(parsed)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
