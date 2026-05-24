"""Stress-test the schema across multiple cricket formats.

Picks a few representative matches (Test, ODI, T20I, women's, club),
parses each, and reports success or failure with the validation error.
Run this before scaling parsing to all 21,800 matches — if every
representative parses cleanly, we have confidence in the schema.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import ValidationError

from sillypoint.config import CRICSHEET_DIR
from sillypoint.ingestion.schema import load_match


def find_match_of_type(
    snapshot_dir: Path,
    match_type: str | None = None,
    gender: str | None = None,
    event_substring: str | None = None,
    limit: int = 1,
) -> list[Path]:
    """Find matches matching the given criteria, returning up to `limit`
    file paths. Reads only the .info block per file for speed.
    """
    found: list[Path] = []
    for path in snapshot_dir.glob("*.json"):
        if len(found) >= limit:
            break
        try:
            with path.open() as f:
                data = json.load(f)
            info = data.get("info", {})
            if match_type and info.get("match_type") != match_type:
                continue
            if gender and info.get("gender") != gender:
                continue
            if event_substring:
                event_name = (info.get("event") or {}).get("name", "")
                if event_substring.lower() not in event_name.lower():
                    continue
            found.append(path)
        except (json.JSONDecodeError, OSError):
            continue
    return found


def try_parse(path: Path, label: str) -> bool:
    """Attempt to parse `path` as a Match, printing success or a clipped
    error. Returns True on success."""
    try:
        match = load_match(path)
        print(f"  ✓ {label}: {path.name}")
        print(
            f"      type={match.info.match_type}, "
            f"teams={' vs '.join(match.info.teams)}, "
            f"date={match.info.dates[0]}, "
            f"innings={len(match.innings)}"
        )
        return True
    except ValidationError as e:
        print(f"  ✗ {label}: {path.name}")
        # Print first 3 errors with their paths — usually enough to debug.
        for err in e.errors()[:3]:
            loc = ".".join(str(p) for p in err["loc"])
            print(f"      {loc}: {err['msg']}")
        return False


def main() -> int:
    snapshot_dir = CRICSHEET_DIR / "2026-05-23" / "matches"
    if not snapshot_dir.exists():
        print(f"ERROR: snapshot not found at {snapshot_dir}", file=sys.stderr)
        return 1
    
    print(f"Scanning {snapshot_dir} for representative matches...\n")
    
    test_cases = [
        ("Men's Test", {"match_type": "Test", "gender": "male"}),
        ("Men's ODI", {"match_type": "ODI", "gender": "male"}),
        ("Men's T20I", {"match_type": "IT20", "gender": "male"}),
        ("Men's T20 league", {"match_type": "T20", "gender": "male"}),
        ("Women's Test", {"match_type": "Test", "gender": "female"}),
        ("Women's ODI", {"match_type": "ODI", "gender": "female"}),
        ("Women's T20I", {"match_type": "IT20", "gender": "female"}),
        ("Women's T20 league", {"match_type": "T20", "gender": "female"}),
        ("The Hundred (100-ball)", {"match_type": "100"}),
        ("Multi-day domestic", {"match_type": "MDM"}),
        ("One-day domestic", {"match_type": "ODM"}),
    ]
    
    successes = 0
    failures = 0
    
    for label, criteria in test_cases:
        matches = find_match_of_type(snapshot_dir, limit=1, **criteria)
        if not matches:
            print(f"  - {label}: no matches found")
            continue
        if try_parse(matches[0], label):
            successes += 1
        else:
            failures += 1
        print()
    
    print(f"\nResults: {successes} passed, {failures} failed")
    return 0 if failures == 0 else 2


if __name__ == "__main__":
    sys.exit(main())