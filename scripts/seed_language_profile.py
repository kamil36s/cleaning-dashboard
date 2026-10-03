"""Explicit, idempotent seed for the initial Norwegian Bokmål profile."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from language_learning import LanguageService, LanguageStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=ROOT / "data" / "language-learning.sqlite")
    args = parser.parse_args()
    service = LanguageService(LanguageStore(args.database))
    service.initialize()
    result = service.ensure_bokmal_profile()
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
