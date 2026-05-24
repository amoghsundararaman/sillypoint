"""Ten cricket-nerd queries against the combined deliveries Parquet.

Each query is chosen to either (a) tell a real cricket story or (b)
demonstrate a column that the parser worked hard to denormalize.
"""

from __future__ import annotations

import sys
import time

import duckdb

from sillypoint.config import PROCESSED_DIR


def run(con: duckdb.DuckDBPyConnection, label: str, sql: str) -> None:
    print(f"\n── {label} " + "─" * max(0, 80 - len(label) - 4))
    start = time.perf_counter()
    result = con.execute(sql).pl()
    elapsed_ms = (time.perf_counter() - start) * 1000
    print(result)
    print(f"({elapsed_ms:.1f} ms)")


def main() -> int:
    deliveries_path = (
        PROCESSED_DIR / "cricsheet" / "2026-05-23" / "deliveries.parquet"
    )
    con = duckdb.connect(":memory:")
    con.execute(f"""
        CREATE VIEW deliveries AS
        SELECT * FROM read_parquet('{deliveries_path}')
    """)

    # 1. Kohli's career arc by year — total runs and matches per calendar year.
    #    Shows the volume curve: when did Kohli become The Kohli?
    run(con, "Kohli's career arc by year", """
        SELECT
            EXTRACT(YEAR FROM match_date) AS year,
            COUNT(DISTINCT match_id) AS matches,
            SUM(runs_batter) AS runs,
            ROUND(SUM(runs_batter) * 1.0 / COUNT(DISTINCT match_id), 1) AS runs_per_match,
            SUM(CASE WHEN runs_batter = 4 THEN 1 ELSE 0 END) AS fours,
            SUM(CASE WHEN runs_batter = 6 THEN 1 ELSE 0 END) AS sixes
        FROM deliveries
        WHERE batter_id = 'ba607b88'
        GROUP BY year
        ORDER BY year
    """)

    # 2. Kohli by phase, T20 only — does he score equally everywhere
    #    or is he secretly a powerplay/anchor specialist?
    run(con, "Kohli's T20 performance by phase", """
        SELECT
            phase,
            COUNT(*) FILTER (WHERE is_legal_ball) AS balls,
            SUM(runs_batter) AS runs,
            ROUND(SUM(runs_batter) * 100.0 / NULLIF(COUNT(*) FILTER (WHERE is_legal_ball), 0), 1) AS strike_rate,
            ROUND(AVG(runs_batter), 3) AS avg_runs_per_ball
        FROM deliveries
        WHERE batter_id = 'ba607b88'
          AND match_type IN ('T20', 'IT20')
        GROUP BY phase
        ORDER BY
            CASE phase
                WHEN 'powerplay' THEN 1
                WHEN 'middle' THEN 2
                WHEN 'death' THEN 3
                ELSE 4
            END
    """)

    # 3. Anderson's longevity — wickets per year of his career, showing
    #    how long he kept performing at international level.
    run(con, "Anderson's wickets per year", """
        SELECT
            EXTRACT(YEAR FROM match_date) AS year,
            COUNT(DISTINCT match_id) AS matches,
            COUNT(*) FILTER (
                WHERE is_wicket
                  AND wicket_kind IN ('caught','bowled','lbw','stumped','caught and bowled','hit wicket')
            ) AS wickets,
            ROUND(
                SUM(runs_batter + extras_wides + extras_noballs + extras_penalty)
                * 6.0 / NULLIF(COUNT(*) FILTER (WHERE is_legal_ball), 0),
                2
            ) AS economy
        FROM deliveries
        WHERE bowler_id = 'd12143bf'
        GROUP BY year
        ORDER BY year
    """)

    # 4. Best men's IPL death-over bowlers — correcting the women's-cricket
    #    skew from the earlier global query. Filtered to IPL event name.
    run(con, "Best men's IPL death-over bowlers (≥300 balls)", """
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
        WHERE event_name = 'Indian Premier League'
          AND phase = 'death'
          AND gender = 'male'
        GROUP BY bowler, bowler_id
        HAVING COUNT(*) FILTER (WHERE is_legal_ball) >= 300
        ORDER BY economy ASC
        LIMIT 15
    """)

    # 5. Most prolific six-hitters — and their balls-per-six. Pure power
    #    rankings; Gayle, Russell, Pollard etc. expected to dominate.
    run(con, "Most prolific six-hitters in T20 cricket", """
        SELECT
            batter,
            batter_id,
            COUNT(*) FILTER (WHERE runs_batter = 6) AS sixes,
            COUNT(*) FILTER (WHERE is_legal_ball) AS balls_faced,
            ROUND(
                COUNT(*) FILTER (WHERE is_legal_ball) * 1.0
                / NULLIF(COUNT(*) FILTER (WHERE runs_batter = 6), 0),
                1
            ) AS balls_per_six
        FROM deliveries
        WHERE match_type IN ('T20', 'IT20')
        GROUP BY batter, batter_id
        HAVING COUNT(*) FILTER (WHERE runs_batter = 6) >= 100
        ORDER BY sixes DESC
        LIMIT 15
    """)

    # 6. Highest team totals per format. SUM(runs_total) per match+innings,
    #    then sort. The denormalized batting_team column makes this trivial.
    run(con, "Highest team totals per format (top 10 each, limit 30 rows)", """
        WITH innings_totals AS (
            SELECT
                match_id,
                innings_idx,
                batting_team,
                bowling_team,
                match_type,
                match_date,
                event_name,
                SUM(runs_total) AS total,
                COUNT(*) FILTER (WHERE is_legal_ball) AS balls,
                COUNT(*) FILTER (WHERE is_wicket) AS wickets
            FROM deliveries
            WHERE match_type IN ('T20','ODI','Test')
            GROUP BY match_id, innings_idx, batting_team, bowling_team,
                     match_type, match_date, event_name
        ),
        ranked AS (
            SELECT
                *,
                ROW_NUMBER() OVER (PARTITION BY match_type ORDER BY total DESC) AS rk
            FROM innings_totals
        )
        SELECT match_type, total, wickets, balls,
               batting_team, bowling_team, match_date, event_name
        FROM ranked
        WHERE rk <= 10
        ORDER BY match_type, total DESC
    """)

    # 7. Most expensive over ever bowled. Group by match/innings/over,
    #    sum runs. Showcases the denormalized columns: we don't need to
    #    re-derive over-level stats — they're already there per row.
    run(con, "Most expensive single overs ever", """
        WITH over_totals AS (
            SELECT
                match_id, innings_idx, over_idx, bowler, batting_team,
                match_date, event_name, match_type,
                SUM(runs_total) AS over_runs,
                COUNT(*) FILTER (WHERE is_legal_ball) AS legal_balls
            FROM deliveries
            GROUP BY match_id, innings_idx, over_idx, bowler, batting_team,
                     match_date, event_name, match_type
        )
        SELECT * FROM over_totals
        WHERE legal_balls >= 6  -- exclude truncated overs
        ORDER BY over_runs DESC
        LIMIT 10
    """)

    # 8. Highest individual innings ever. striker_balls_so_far + runs at
    #    end-of-innings gives each batter's final score per innings.
    #    We take max per (match_id, innings_idx, batter_id).
    run(con, "Highest individual innings ever", """
        WITH batter_final AS (
            SELECT
                match_id,
                innings_idx,
                batter,
                batter_id,
                batting_team,
                match_type,
                match_date,
                event_name,
                SUM(runs_batter) AS runs,
                COUNT(*) FILTER (WHERE is_legal_ball) AS balls
            FROM deliveries
            GROUP BY match_id, innings_idx, batter, batter_id, batting_team,
                     match_type, match_date, event_name
        )
        SELECT
            batter, runs, balls,
            ROUND(runs * 100.0 / NULLIF(balls, 0), 1) AS strike_rate,
            batting_team, match_type, match_date, event_name
        FROM batter_final
        ORDER BY runs DESC
        LIMIT 15
    """)

    # 9. Free-hit conversion: when batters get a free hit (the next ball
    #    after a no-ball), how often do they capitalize? Compare runs
    #    per ball on free hits vs all other balls.
    run(con, "Free-hit conversion: scoring rate vs normal balls", """
        SELECT
            is_free_hit,
            COUNT(*) AS balls,
            SUM(runs_batter) AS runs,
            ROUND(SUM(runs_batter) * 1.0 / COUNT(*), 3) AS runs_per_ball,
            SUM(CASE WHEN runs_batter = 4 THEN 1 ELSE 0 END) AS fours,
            SUM(CASE WHEN runs_batter = 6 THEN 1 ELSE 0 END) AS sixes,
            ROUND(SUM(CASE WHEN runs_batter IN (4,6) THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS boundary_pct
        FROM deliveries
        WHERE is_legal_ball
          AND match_type IN ('T20', 'IT20', 'ODI')
        GROUP BY is_free_hit
        ORDER BY is_free_hit DESC
    """)

    # 10. Best batter–bowler matchups by volume: who has faced whom the
    #     most balls? Showcase the foundation-model premise — these
    #     long matchups are where patterns emerge that a transformer
    #     could learn beyond surface stats.
    run(con, "Top batter–bowler matchups by ball count", """
        SELECT
            batter,
            bowler,
            COUNT(*) FILTER (WHERE is_legal_ball) AS balls,
            SUM(runs_batter) AS runs,
            ROUND(SUM(runs_batter) * 100.0 / NULLIF(COUNT(*) FILTER (WHERE is_legal_ball), 0), 1) AS strike_rate,
            COUNT(*) FILTER (
                WHERE is_wicket
                  AND wicket_kind IN ('caught','bowled','lbw','stumped','caught and bowled','hit wicket')
            ) AS dismissals
        FROM deliveries
        WHERE batter_id IS NOT NULL AND bowler_id IS NOT NULL
        GROUP BY batter, bowler
        HAVING COUNT(*) FILTER (WHERE is_legal_ball) >= 200
        ORDER BY balls DESC
        LIMIT 15
    """)

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())