"""First exploration of the combined deliveries Parquet via DuckDB.

Runs a handful of sanity-check queries plus a few genuinely interesting
ones. Output is meant to be eyeballed for both correctness (do the
numbers make sense?) and cricket interest (do the answers tell a real
story?).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import duckdb

from sillypoint.config import PROCESSED_DIR


def run(con: duckdb.DuckDBPyConnection, label: str, sql: str) -> None:
    """Run a SQL query, print the label, time it, show the result."""
    print(f"\n── {label} " + "─" * (76 - len(label)))
    start = time.perf_counter()
    result = con.execute(sql).pl()
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(result)
    print(f"({elapsed_ms:.1f} ms)")


def main() -> int:
    deliveries_path = (
        PROCESSED_DIR / "cricsheet" / "2026-05-23" / "deliveries.parquet"
    )
    if not deliveries_path.exists():
        print(f"ERROR: {deliveries_path} not found", file=sys.stderr)
        return 1
    
    con = duckdb.connect(":memory:")
    # Make the Parquet queryable as a table named `deliveries`
    con.execute(f"""
        CREATE VIEW deliveries AS
        SELECT * FROM read_parquet('{deliveries_path}')
    """)
    
    # 1. Sanity: total row count
    run(con, "Total deliveries", """
        SELECT COUNT(*) AS total_deliveries FROM deliveries
    """)
    
    # 2. Deliveries by match type
    run(con, "Deliveries by match type", """
        SELECT
            match_type,
            COUNT(DISTINCT match_id) AS matches,
            COUNT(*) AS deliveries,
            ROUND(COUNT(*) * 1.0 / COUNT(DISTINCT match_id), 1) AS avg_deliveries_per_match
        FROM deliveries
        GROUP BY match_type
        ORDER BY deliveries DESC
    """)
    
    # 3. Top 10 run-scorers across all cricket in our snapshot
    run(con, "Top 10 run-scorers (all formats, all time)", """
        SELECT
            batter,
            batter_id,
            SUM(runs_batter) AS runs,
            COUNT(*) FILTER (WHERE is_legal_ball) AS balls_faced,
            COUNT(DISTINCT match_id) AS matches
        FROM deliveries
        WHERE batter_id IS NOT NULL
        GROUP BY batter, batter_id
        ORDER BY runs DESC
        LIMIT 10
    """)
    
    # 4. Top 10 wicket-takers (only credited dismissal types)
    run(con, "Top 10 wicket-takers (all formats, all time)", """
        SELECT
            bowler,
            bowler_id,
            COUNT(*) AS wickets,
            COUNT(DISTINCT match_id) AS matches
        FROM deliveries
        WHERE is_wicket
          AND wicket_kind IN ('caught','bowled','lbw','stumped','caught and bowled','hit wicket')
          AND bowler_id IS NOT NULL
        GROUP BY bowler, bowler_id
        ORDER BY wickets DESC
        LIMIT 10
    """)
    
    # 5. Death-overs specialists: lowest economy in T20 death overs, min 500 balls
    run(con, "Best T20 death-over bowlers (≥500 balls bowled in T20 death)", """
        SELECT
            bowler,
            bowler_id,
            COUNT(*) FILTER (WHERE is_legal_ball) AS balls,
            SUM(runs_batter + extras_wides + extras_noballs + extras_penalty) AS runs_conceded,
            ROUND(
                SUM(runs_batter + extras_wides + extras_noballs + extras_penalty)
                * 6.0 / NULLIF(COUNT(*) FILTER (WHERE is_legal_ball), 0),
                2
            ) AS economy,
            COUNT(*) FILTER (
                WHERE is_wicket
                  AND wicket_kind IN ('caught','bowled','lbw','stumped','caught and bowled','hit wicket')
            ) AS wickets
        FROM deliveries
        WHERE match_type IN ('T20','IT20')
          AND phase = 'death'
          AND bowler_id IS NOT NULL
        GROUP BY bowler, bowler_id
        HAVING COUNT(*) FILTER (WHERE is_legal_ball) >= 500
        ORDER BY economy ASC
        LIMIT 15
    """)
    
    # 6. The SRH vs PBKS game we know
    run(con, "Our reference match: SRH vs PBKS, 2026-05-06", """
        SELECT
            innings_idx,
            batting_team,
            SUM(runs_total) AS total_runs,
            COUNT(*) FILTER (WHERE is_legal_ball) AS legal_balls,
            COUNT(*) FILTER (WHERE is_wicket) AS wickets
        FROM deliveries
        WHERE match_id = '1529292'
        GROUP BY innings_idx, batting_team
        ORDER BY innings_idx
    """)
    
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())