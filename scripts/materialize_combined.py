"""Materialize all per-match Parquet files into a single combined
Parquet that holds every delivery in the snapshot.

This is the file DuckDB reads for fast analytical queries. It's a
derived artifact, fully reproducible from the per-match Parquets, so
it's safe to delete and regenerate.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import polars as pl
from tqdm import tqdm

from sillypoint.config import PROCESSED_DIR


logger = logging.getLogger(__name__)


def main() -> int:
    snapshot_date = "2026-05-23"
    per_match_dir = (
        PROCESSED_DIR / "cricsheet" / snapshot_date / "matches"
    )
    output_path = (
        PROCESSED_DIR / "cricsheet" / snapshot_date / "deliveries.parquet"
    )
    
    if not per_match_dir.exists():
        print(f"ERROR: {per_match_dir} not found", file=sys.stderr)
        return 1
    
    paths = sorted(per_match_dir.glob("*.parquet"))
    print(f"Found {len(paths)} per-match Parquet files.")
    print(f"Materializing to {output_path}\n")
    
    # Use Polars's lazy API: scan all files into a LazyFrame, then sink
    # to a single Parquet. This streams the data so we don't load all
    # 4M rows into memory at once.
    lf = pl.scan_parquet(per_match_dir / "*.parquet")
    
    print("Streaming combined file to disk (this can take a minute)...")
    lf.sink_parquet(output_path, compression="zstd")
    
    # Confirm with a quick read-back
    df = pl.scan_parquet(output_path).select(pl.len()).collect()
    total_rows = df.item()
    
    size_bytes = output_path.stat().st_size
    print(f"\n✓ Combined Parquet written: {output_path}")
    print(f"  Total rows: {total_rows:,}")
    print(f"  File size: {size_bytes / 1024 / 1024:.1f} MB")
    
    return 0


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(main())