"""Parse the SRH vs PBKS match (1529292) and verify the parser produces
the expected totals.

Expected:
- First innings total = 235
- 2 innings, batters scoring known runs
- Cummins as bowler with 2 wickets, ~25 balls
"""

from __future__ import annotations

import sys

from sillypoint.config import CRICSHEET_DIR
from sillypoint.ingestion.parser import parse_match_to_deliveries
from sillypoint.ingestion.schema import load_match


def main() -> int:
    snapshot_dir = CRICSHEET_DIR / "2026-05-23" / "matches"
    match_path = snapshot_dir / "1529292.json"
    
    match = load_match(match_path)
    rows = parse_match_to_deliveries(match)
    
    print(f"Parser produced {len(rows)} deliveries.")
    print(f"Match: {match.info.teams[0]} vs {match.info.teams[1]}, "
          f"{match.info.dates[0]}")
    print()
    
    # Innings totals
    innings_0_total = sum(r["runs_total"] for r in rows if r["innings_idx"] == 0)
    innings_1_total = sum(r["runs_total"] for r in rows if r["innings_idx"] == 1)
    print(f"Innings 0 ({match.innings[0].team}) total: {innings_0_total}")
    print(f"Innings 1 ({match.innings[1].team}) total: {innings_1_total}")
    print(f"Margin: {innings_0_total - innings_1_total} runs")
    
    # Cummins line
    cummins_rows = [r for r in rows if r["bowler_id"] == "ded9240e"]
    cummins_legal = [r for r in cummins_rows if r["is_legal_ball"]]
    cummins_runs_conceded = sum(
        r["runs_batter"] + r["extras_wides"] + r["extras_noballs"] + r["extras_penalty"]
        for r in cummins_rows
    )
    cummins_wickets = sum(
        1 for r in cummins_rows
        if r["is_wicket"] and r["wicket_kind"] in {
            "caught", "bowled", "lbw", "stumped", "caught and bowled", "hit wicket"
        }
    )
    print(f"\nCummins line: {cummins_wickets}/{cummins_runs_conceded} "
          f"off {len(cummins_legal)} balls ({len(cummins_rows)} including extras)")
    
    # Top scorer first innings
    from collections import defaultdict
    bat_totals: dict[str, int] = defaultdict(int)
    for r in rows:
        if r["innings_idx"] == 0:
            bat_totals[r["batter"]] += r["runs_batter"]
    top_5 = sorted(bat_totals.items(), key=lambda x: -x[1])[:5]
    print(f"\nTop 5 scorers, innings 0:")
    for name, runs in top_5:
        print(f"  {name}: {runs}")
    
    # Phase distribution
    from collections import Counter
    phase_counts = Counter(r["phase"] for r in rows)
    print(f"\nPhase distribution: {dict(phase_counts)}")
    
    # Sanity assertions
    assert innings_0_total == 235, f"Expected 235, got {innings_0_total}"
    assert innings_0_total - innings_1_total == 33, f"Expected margin 33, got {innings_0_total - innings_1_total}"
    
    print(f"\n✓ All sanity checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())