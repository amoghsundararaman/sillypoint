"""Sample N random matches from the snapshot and parse each.

Reports overall pass/fail counts and prints the first error per failed
match. Run this after the breadth test passes to catch rare quirks
that single representatives might miss.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from pydantic import ValidationError

from sillypoint.config import CRICSHEET_DIR
from sillypoint.ingestion.schema import load_match


SAMPLE_SIZE = 100
RANDOM_SEED = 42  # reproducibility — same sample every time


def main() -> int:
    snapshot_dir = CRICSHEET_DIR / "2026-05-23" / "matches"
    if not snapshot_dir.exists():
        print(f"ERROR: snapshot not found at {snapshot_dir}", file=sys.stderr)
        return 1
    
    all_paths = list(snapshot_dir.glob("*.json"))
    print(f"Snapshot contains {len(all_paths)} matches.")
    
    rng = random.Random(RANDOM_SEED)
    sample = rng.sample(all_paths, min(SAMPLE_SIZE, len(all_paths)))
    print(f"Sampling {len(sample)} matches with seed={RANDOM_SEED}...\n")
    
    passes: list[str] = []
    failures: list[tuple[str, str]] = []  # (filename, summary of first error)
    
    for path in sample:
        try:
            load_match(path)
            passes.append(path.name)
        except ValidationError as e:
            first_err = e.errors()[0]
            loc = ".".join(str(p) for p in first_err["loc"])
            msg = first_err["msg"]
            failures.append((path.name, f"{loc}: {msg}"))
        except Exception as e:
            failures.append((path.name, f"non-validation error: {type(e).__name__}: {e}"))
    
    print(f"Passed: {len(passes)}")
    print(f"Failed: {len(failures)}\n")
    
    if failures:
        print("Failures (first 20):")
        for name, summary in failures[:20]:
            print(f"  {name}: {summary}")
    
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(main())