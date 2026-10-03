"""Back up canonical pilot data without copying an incomplete WAL snapshot."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dashboard_sync.backup import backup_database

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', type=Path, default=Path('data/journal.sqlite'))
    parser.add_argument('--destination', type=Path)
    args = parser.parse_args()
    print(json.dumps(backup_database(args.database, args.destination), indent=2))
