"""Parse every match in the Cricsheet snapshot and write one Parquet per
match to data/processed/cricsheet/<snapshot_date>/.

Failures are logged to a separate JSON file so we can audit them
without losing the ones that worked.
"""

from __future__ import annotations

import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
from pydantic import ValidationError
from tqdm import tqdm

from sillypoint.config import CRICSHEET_DIR, PROCESSED_DIR
from sillypoint.ingestion.parser import (
    parse_match_to_deliveries,
    DELIVERY_SCHEMA,
)
from sillypoint.ingestion.schema import load_match


logger = logging.getLogger(__name__)


def parse_one(json_path: Path, output_path: Path) -> tuple[bool, str | None]:
    """Parse a single match and write its Parquet. Returns (success, error_msg)."""
    try:
        match = load_match(json_path)
        rows = parse_match_to_deliveries(match)
        # Empty rows is valid — match was abandoned before any ball was
        # bowled, or all innings forfeited. Write an empty Parquet so
        # downstream code knows the match existed.
        # Override match_id with the actual filename for stability
        # (the parser's fallback was for callers that don't know the ID).
        match_id_from_filename = json_path.stem
        for row in rows:
            old_id = row["match_id"]
            row["match_id"] = match_id_from_filename
            row["delivery_id"] = row["delivery_id"].replace(old_id, match_id_from_filename)
        df = pl.from_dicts(rows, schema=DELIVERY_SCHEMA)
        df.write_parquet(output_path)
        return True, None
    except ValidationError as e:
        first = e.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        return False, f"ValidationError at {loc}: {first['msg']}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main() -> int:
    snapshot_date = "2026-05-23"
    snapshot_dir = CRICSHEET_DIR / snapshot_date / "matches"
    output_dir = PROCESSED_DIR / "cricsheet" / snapshot_date / "matches"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if not snapshot_dir.exists():
        print(f"ERROR: snapshot not found at {snapshot_dir}", file=sys.stderr)
        return 1
    
    paths = sorted(snapshot_dir.glob("*.json"))
    print(f"Found {len(paths)} matches in snapshot {snapshot_date}")
    print(f"Writing Parquet files to {output_dir}\n")
    
    failures: list[dict] = []
    success_count = 0
    skipped_count = 0
    
    for path in tqdm(paths, desc="Parsing"):
        out_path = output_dir / f"{path.stem}.parquet"
        if out_path.exists():
            skipped_count += 1
            continue
        ok, err = parse_one(path, out_path)
        if ok:
            success_count += 1
        else:
            failures.append({
                "match_id": path.stem,
                "file": str(path),
                "error": err,
            })
    
    # Write failures log
    failures_log = (
        PROCESSED_DIR / "cricsheet" / snapshot_date / "parse_failures.json"
    )
    with failures_log.open("w") as f:
        json.dump(
            {
                "snapshot_date": snapshot_date,
                "run_at_utc": datetime.now(timezone.utc).isoformat(),
                "total_matches": len(paths),
                "succeeded": success_count,
                "skipped_existing": skipped_count,
                "failed": len(failures),
                "failures": failures,
            },
            f,
            indent=2,
        )
    
    print(f"\nSucceeded: {success_count}")
    print(f"Skipped (already existed): {skipped_count}")
    print(f"Failed: {len(failures)}")
    print(f"Failure log: {failures_log}")
    
    if failures:
        print("\nFirst 10 failures:")
        for fail in failures[:10]:
            print(f"  {fail['match_id']}: {fail['error']}")
    
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(main())