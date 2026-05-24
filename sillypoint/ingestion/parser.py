"""Cricsheet match parser: transforms validated Match (Layer 1) into a
flat list of delivery records (Layer 2).

Each delivery becomes a single dict with ~70 columns covering:
- Identifiers (delivery_id, match_id, innings_idx, over_idx, etc.)
- Match context (date, venue, teams)
- Players (with both short names and UUIDs)
- Ball outcome (runs, extras, wickets)
- Pre-state (innings totals, batter/bowler state, partnership, chase context)
- Phase (powerplay/middle/death + within-phase counters)
- Over-level state
- Recent context (last-ball/last-over signals for momentum features)

The pre-state is captured *before* each ball updates the running totals.
This ordering is what allows the foundation model to learn: each row
represents 'the state of the world going into this ball, plus what
happened next.'

Enricher fields (weather, pitch, shot type, etc.) are populated as None
by this parser and filled in later by dedicated enricher modules.
"""
# Explicit column schema for the flat delivery table. Passing this to
# Polars on construction prevents type-inference flakiness when early
# rows happen to be all-null for columns that fill in later (DRS reviews,
# wickets, etc.). It's also the canonical specification of what each
# column means — keep this in sync with the row dict in _parse_innings.
from __future__ import annotations
import polars as pl

DELIVERY_SCHEMA: dict[str, pl.DataType] = {
    # Identifiers
    "delivery_id": pl.Utf8,
    "match_id": pl.Utf8,
    "innings_idx": pl.Int32,
    "over_idx": pl.Int32,
    "delivery_idx_in_over": pl.Int32,
    "legal_ball_in_over": pl.Int32,  # nullable
    
    # Match context
    "match_date": pl.Date,
    "match_type": pl.Utf8,
    "venue": pl.Utf8,
    "city": pl.Utf8,
    "gender": pl.Utf8,
    "event_name": pl.Utf8,
    "season": pl.Utf8,
    "batting_team": pl.Utf8,
    "bowling_team": pl.Utf8,
    
    # Players
    "batter": pl.Utf8,
    "batter_id": pl.Utf8,
    "non_striker": pl.Utf8,
    "non_striker_id": pl.Utf8,
    "bowler": pl.Utf8,
    "bowler_id": pl.Utf8,
    
    # Ball outcome
    "runs_batter": pl.Int32,
    "runs_extras": pl.Int32,
    "runs_total": pl.Int32,
    "extras_wides": pl.Int32,
    "extras_noballs": pl.Int32,
    "extras_byes": pl.Int32,
    "extras_legbyes": pl.Int32,
    "extras_penalty": pl.Int32,
    "is_legal_ball": pl.Boolean,
    "is_wicket": pl.Boolean,
    "wicket_kind": pl.Utf8,
    "player_out": pl.Utf8,
    "player_out_id": pl.Utf8,
    "fielders_involved": pl.List(pl.Utf8),
    
    # Innings state
    "runs_so_far_innings": pl.Int32,
    "wickets_so_far_innings": pl.Int32,
    "legal_balls_bowled_in_innings": pl.Int32,
    "balls_remaining_in_innings": pl.Int32,
    
    # Striker/non-striker state
    "striker_runs_so_far": pl.Int32,
    "striker_balls_so_far": pl.Int32,
    "striker_is_new": pl.Boolean,
    "non_striker_runs_so_far": pl.Int32,
    "non_striker_balls_so_far": pl.Int32,
    
    # Partnership
    "partnership_runs_so_far": pl.Int32,
    "partnership_balls_so_far": pl.Int32,
    
    # Bowler state
    "bowler_runs_conceded_so_far": pl.Int32,
    "bowler_wickets_so_far": pl.Int32,
    "bowler_balls_bowled_so_far": pl.Int32,
    "bowler_is_new_to_attack": pl.Boolean,
    
    # Chase context
    "target": pl.Int32,
    "runs_to_win": pl.Int32,
    "required_run_rate": pl.Float64,
    
    # Phase
    "phase": pl.Utf8,
    "balls_into_phase": pl.Int32,
    "overs_into_phase": pl.Int32,
    "is_phase_transition": pl.Boolean,
    "test_session": pl.Utf8,
    "test_day": pl.Int32,
    
    # Over-level state
    "over_runs_so_far": pl.Int32,
    "over_legal_balls_so_far": pl.Int32,
    "is_first_ball_of_over": pl.Boolean,
    "is_last_ball_of_over": pl.Boolean,
    
    # Recent context
    "last_ball_was_dot": pl.Boolean,
    "last_ball_was_boundary": pl.Boolean,
    "last_ball_was_wicket": pl.Boolean,
    "runs_in_last_over": pl.Int32,
    "wickets_in_last_over": pl.Int32,
    
    # Special states
    "is_free_hit": pl.Boolean,
    "is_super_over": pl.Boolean,
    
    # DRS state
    "drs_reviews_remaining_batting": pl.Int32,
    "drs_reviews_remaining_bowling": pl.Int32,
    "review_taken": pl.Boolean,
    "review_outcome": pl.Utf8,
    "review_by": pl.Utf8,
    
    # Enricher-populated fields (typed even though always-null at parse time)
    "venue_lat": pl.Float64,
    "venue_lon": pl.Float64,
    "temperature_c": pl.Float64,
    "humidity_pct": pl.Float64,
    "wind_speed_kmh": pl.Float64,
    "wind_direction_deg": pl.Float64,
    "precipitation_mm": pl.Float64,
    "cloud_cover_pct": pl.Float64,
    "dew_point_c": pl.Float64,
    "dew_likely_score": pl.Float64,
    "match_start_time_local": pl.Utf8,  # store as "HH:MM" string
    "sunrise_local": pl.Utf8,
    "sunset_local": pl.Utf8,
    "is_day_session": pl.Boolean,
    "is_night_session": pl.Boolean,
    "is_twilight": pl.Boolean,
    "venue_capacity": pl.Int32,
    "crowd_attendance": pl.Int32,
    "crowd_noise_db": pl.Float64,
    "pitch_report_text": pl.Utf8,
    "pitch_report_features": pl.Utf8,  # JSON-as-string for now
    "pitch_type": pl.Utf8,
    "bowler_style": pl.Utf8,
    "bowler_pace_category": pl.Utf8,
    "bowler_arm": pl.Utf8,
    "bowler_spin_type": pl.Utf8,
    "boundary_length_short_m": pl.Float64,
    "boundary_length_long_m": pl.Float64,
    "boundary_straight_m": pl.Float64,
    "shot_played": pl.Utf8,
    "shot_zone": pl.Utf8,
    "field_positions": pl.Utf8,  # JSON-as-string for now
}


from datetime import date
from typing import Any

from sillypoint.ingestion.schema import (
    Delivery,
    Innings,
    Match,
    Over,
    Wicket,
)





# Powerplay over boundaries by match type. Each entry maps a match type
# to (powerplay_end_over_exclusive, death_start_over). Over indices are
# 0-based throughout. Limited-overs cricket; Tests get "normal" phase.
PHASE_BOUNDARIES: dict[str, tuple[int, int]] = {
    "T20": (6, 16),    # PP: overs 0-5, middle: 6-15, death: 16-19
    "IT20": (6, 16),
    "ODI": (10, 40),   # PP: 0-9, middle: 10-39, death: 40-49
    "ODM": (10, 40),
    "100": (5, 16),    # 100-ball: PP first 25 balls (5 "overs" of 5),
                       # death last 25 balls
}

# DRS reviews available per team per innings, by match type. This is
# rule-of-thumb; modern matches often have 2 per innings for T20s and
# 3 for Tests but rules change. We default to 2 and accept some inaccuracy
# for very old matches.
DRS_REVIEWS_PER_INNINGS: dict[str, int] = {
    "Test": 3,
    "ODI": 2,
    "ODM": 2,
    "IT20": 2,
    "T20": 2,
    "MDM": 0,  # most domestic multi-day matches: no DRS
    "100": 1,
}


def _phase_for(match_type: str, over_idx: int) -> str:
    """Return the fielding-restriction phase for a given over."""
    boundaries = PHASE_BOUNDARIES.get(match_type)
    if boundaries is None:
        return "normal"
    pp_end, death_start = boundaries
    if over_idx < pp_end:
        return "powerplay"
    if over_idx >= death_start:
        return "death"
    return "middle"


def _is_legal_ball(delivery: Delivery) -> bool:
    """A delivery is 'legal' (counts toward the over) if it's not a wide
    or no-ball. Byes and leg-byes ARE legal balls."""
    if delivery.extras is None:
        return True
    if delivery.extras.wides:
        return False
    if delivery.extras.noballs:
        return False
    return True


def _extract_wicket_info(
    delivery: Delivery,
    registry: dict[str, str],
) -> dict[str, Any]:
    """Pull wicket info out of a delivery, returning a dict with keys
    `is_wicket`, `wicket_kind`, `player_out`, `player_out_id`,
    `fielders_involved`. Handles the rare two-wickets-one-ball case by
    taking the first."""
    if not delivery.wickets:
        return {
            "is_wicket": False,
            "wicket_kind": None,
            "player_out": None,
            "player_out_id": None,
            "fielders_involved": None,
        }
    first: Wicket = delivery.wickets[0]
    fielders = (
        [f.name for f in first.fielders if f.name]
        if first.fielders
        else None
    )
    return {
        "is_wicket": True,
        "wicket_kind": first.kind,
        "player_out": first.player_out,
        "player_out_id": registry.get(first.player_out),
        "fielders_involved": fielders,
    }


def _innings_total(innings: Innings) -> int:
    """Sum total runs in an innings. Used to compute target for innings 1."""
    return sum(
        d.runs.total for over in innings.overs for d in over.deliveries
    )


def parse_match_to_deliveries(match: Match) -> list[dict[str, Any]]:
    """Transform a validated Match into a flat list of delivery records.
    
    Returns a list of dicts (one per delivery) ready for Parquet writing
    or DataFrame construction. Each dict has ~70 keys; enricher fields
    (weather, pitch, etc.) are present as None and filled in by later
    enricher modules.
    """
    info = match.info
    registry = info.registry.people
    match_id = _infer_match_id(match)
    match_date = info.dates[0]
    
    # Target for second innings (and beyond, for Tests): pre-compute the
    # first-innings total. For Tests, target semantics are different (it
    # accumulates across innings); we set target only for innings 1 of
    # limited-overs matches. Tests get None.
    is_limited_overs = info.match_type in {"T20", "IT20", "ODI", "ODM", "100"}
    target = None
    if is_limited_overs and len(match.innings) >= 2:
        target = _innings_total(match.innings[0]) + 1  # need to exceed
    
    rows: list[dict[str, Any]] = []
    
    for innings_idx, innings in enumerate(match.innings):
        rows.extend(
            _parse_innings(
                innings=innings,
                innings_idx=innings_idx,
                match_id=match_id,
                match_date=match_date,
                match_info=info,
                registry=registry,
                target=target if innings_idx == 1 else None,
                bowling_team=_other_team(info.teams, innings.team),
            )
        )
    
    return rows


def _infer_match_id(match: Match) -> str:
    """Extract a stable match identifier. Cricsheet doesn't include the
    numeric file ID inside the JSON itself, so we use a composite of
    date + teams as a fallback for cases where the caller didn't set one.
    Real callers should override this by passing match_id explicitly when
    parsing from a known filename.
    """
    date_str = match.info.dates[0].isoformat()
    teams = "_vs_".join(sorted(match.info.teams))
    return f"{date_str}_{teams}"


def _other_team(teams: list[str], one_team: str) -> str:
    """Return the team that isn't `one_team`."""
    for t in teams:
        if t != one_team:
            return t
    return ""  # shouldn't happen given schema constraint min/max 2 teams


def _parse_innings(
    innings: Innings,
    innings_idx: int,
    match_id: str,
    match_date: date,
    match_info: Any,
    registry: dict[str, str],
    target: int | None,
    bowling_team: str,
) -> list[dict[str, Any]]:
    """Walk a single innings ball-by-ball, emitting one row per delivery.
    
    State tracked across the innings:
    - Innings running totals (runs, wickets, legal balls)
    - Per-batter running stats (runs, balls) keyed by batter name
    - Bowler running stats keyed by bowler name
    - Partnership running totals (resets on each wicket)
    - Phase running counters (resets on phase transition)
    - Recent context: previous ball outcome, previous over totals
    """
    rows: list[dict[str, Any]] = []
    
    # Innings-level running state
    innings_runs = 0
    innings_wickets = 0
    legal_balls_bowled = 0
    
    # Per-player stats accumulate across the innings
    batter_runs: dict[str, int] = {}
    batter_balls: dict[str, int] = {}
    bowler_runs_conceded: dict[str, int] = {}
    bowler_wickets: dict[str, int] = {}
    bowler_balls_bowled: dict[str, int] = {}
    bowlers_seen_in_order: list[str] = []  # to detect new-to-attack bowlers
    
    # Partnership state — resets on each wicket
    partnership_runs = 0
    partnership_balls = 0
    
    # Phase state — resets when over_idx crosses a boundary
    current_phase: str | None = None
    balls_into_phase = 0
    overs_into_phase = 0
    
    # Recent-context memory (initialized to "no prior ball")
    last_ball_was_dot = False
    last_ball_was_boundary = False
    last_ball_was_wicket = False
    
    # Track the previous over's totals (filled at end of each over)
    runs_in_last_over = 0
    wickets_in_last_over = 0
    
    # Within-over state
    over_runs_so_far = 0
    over_legal_balls_so_far = 0
    
    # Innings format-specific context
    match_type = match_info.match_type
    is_limited_overs = match_type in {"T20", "IT20", "ODI", "ODM", "100"}
    overs_per_innings = match_info.overs or 0
    total_balls_in_innings = overs_per_innings * 6 if is_limited_overs else 0
    
    # Free hit tracking: the next legal ball after a front-foot no-ball
    next_ball_is_free_hit = False
    
    # DRS reviews remaining per side this innings (rough)
    reviews_remaining_batting = DRS_REVIEWS_PER_INNINGS.get(match_type, 0)
    reviews_remaining_bowling = DRS_REVIEWS_PER_INNINGS.get(match_type, 0)
    
    for over in innings.overs:
        # Reset within-over state at start of each over
        over_runs_so_far = 0
        over_legal_balls_so_far = 0
        is_first_ball_of_over = True
        
        # Phase transition detection
        new_phase = _phase_for(match_type, over.over)
        is_phase_transition_over = new_phase != current_phase
        if is_phase_transition_over:
            current_phase = new_phase
            balls_into_phase = 0
            overs_into_phase = 0
        
        for delivery_idx, delivery in enumerate(over.deliveries):
            legal_ball = _is_legal_ball(delivery)
            wicket = _extract_wicket_info(delivery, registry)
            
            striker = delivery.batter
            non_striker = delivery.non_striker
            bowler = delivery.bowler
            
            # PRE-STATE: capture everything before this ball updates totals
            striker_runs_so_far = batter_runs.get(striker, 0)
            striker_balls_so_far = batter_balls.get(striker, 0)
            non_striker_runs_so_far = batter_runs.get(non_striker, 0)
            non_striker_balls_so_far = batter_balls.get(non_striker, 0)
            bowler_runs_so_far = bowler_runs_conceded.get(bowler, 0)
            bowler_wickets_so_far = bowler_wickets.get(bowler, 0)
            bowler_balls_so_far = bowler_balls_bowled.get(bowler, 0)
            bowler_is_new = bowler not in bowlers_seen_in_order
            
            # Chase context (innings 1 only, limited-overs only)
            balls_remaining_in_innings: int | None = None
            runs_to_win: int | None = None
            required_run_rate: float | None = None
            if is_limited_overs:
                balls_remaining_in_innings = (
                    total_balls_in_innings - legal_balls_bowled
                )
                if target is not None:
                    runs_to_win = target - innings_runs
                    if balls_remaining_in_innings and balls_remaining_in_innings > 0:
                        required_run_rate = (
                            runs_to_win * 6.0 / balls_remaining_in_innings
                        )
            
            # Extras breakdown
            wides = delivery.extras.wides if delivery.extras else 0
            noballs = delivery.extras.noballs if delivery.extras else 0
            byes = delivery.extras.byes if delivery.extras else 0
            legbyes = delivery.extras.legbyes if delivery.extras else 0
            penalty = delivery.extras.penalty if delivery.extras else 0
            
            # Is this delivery itself a free hit?
            is_free_hit = next_ball_is_free_hit and legal_ball
            # Update free-hit flag for the NEXT ball: a front-foot no-ball
            # triggers a free hit on the next legal delivery.
            if noballs:
                next_ball_is_free_hit = True
            elif legal_ball:
                next_ball_is_free_hit = False
            
            # Construct the row
            row: dict[str, Any] = {
                # Identifiers
                "delivery_id": f"{match_id}-{innings_idx}-{over.over}-{delivery_idx}",
                "match_id": match_id,
                "innings_idx": innings_idx,
                "over_idx": over.over,
                "delivery_idx_in_over": delivery_idx,
                "legal_ball_in_over": (
                    over_legal_balls_so_far + 1 if legal_ball else None
                ),
                
                # Match context
                "match_date": match_date,
                "match_type": match_type,
                "venue": match_info.venue,
                "city": match_info.city,
                "gender": match_info.gender,
                "event_name": (
                    match_info.event.name if match_info.event else None
                ),
                "season": (
                    str(match_info.season) if match_info.season is not None else None
                ),
                "batting_team": innings.team,
                "bowling_team": bowling_team,
                
                # Players
                "batter": striker,
                "batter_id": registry.get(striker),
                "non_striker": non_striker,
                "non_striker_id": registry.get(non_striker),
                "bowler": bowler,
                "bowler_id": registry.get(bowler),
                
                # Ball outcome
                "runs_batter": delivery.runs.batter,
                "runs_extras": delivery.runs.extras,
                "runs_total": delivery.runs.total,
                "extras_wides": wides or 0,
                "extras_noballs": noballs or 0,
                "extras_byes": byes or 0,
                "extras_legbyes": legbyes or 0,
                "extras_penalty": penalty or 0,
                "is_legal_ball": legal_ball,
                **wicket,
                
                # Innings state (pre-state)
                "runs_so_far_innings": innings_runs,
                "wickets_so_far_innings": innings_wickets,
                "legal_balls_bowled_in_innings": legal_balls_bowled,
                "balls_remaining_in_innings": balls_remaining_in_innings,
                
                # Striker / non-striker state (pre-state)
                "striker_runs_so_far": striker_runs_so_far,
                "striker_balls_so_far": striker_balls_so_far,
                "striker_is_new": striker_balls_so_far == 0,
                "non_striker_runs_so_far": non_striker_runs_so_far,
                "non_striker_balls_so_far": non_striker_balls_so_far,
                
                # Partnership (pre-state)
                "partnership_runs_so_far": partnership_runs,
                "partnership_balls_so_far": partnership_balls,
                
                # Bowler state (pre-state)
                "bowler_runs_conceded_so_far": bowler_runs_so_far,
                "bowler_wickets_so_far": bowler_wickets_so_far,
                "bowler_balls_bowled_so_far": bowler_balls_so_far,
                "bowler_is_new_to_attack": bowler_is_new,
                
                # Chase context (innings 1+ of limited overs)
                "target": target,
                "runs_to_win": runs_to_win,
                "required_run_rate": required_run_rate,
                
                # Phase
                "phase": current_phase,
                "balls_into_phase": balls_into_phase,
                "overs_into_phase": overs_into_phase,
                "is_phase_transition": is_phase_transition_over and is_first_ball_of_over,
                "test_session": None,  # filled in later
                "test_day": None,  # filled in later
                
                # Over-level state (pre-state for this ball within its over)
                "over_runs_so_far": over_runs_so_far,
                "over_legal_balls_so_far": over_legal_balls_so_far,
                "is_first_ball_of_over": is_first_ball_of_over,
                "is_last_ball_of_over": False,  # filled in post-pass
                
                # Recent context (momentum signals)
                "last_ball_was_dot": last_ball_was_dot,
                "last_ball_was_boundary": last_ball_was_boundary,
                "last_ball_was_wicket": last_ball_was_wicket,
                "runs_in_last_over": runs_in_last_over,
                "wickets_in_last_over": wickets_in_last_over,
                
                # Special states
                "is_free_hit": is_free_hit,
                "is_super_over": innings.super_over or False,
                
                # DRS state
                "drs_reviews_remaining_batting": reviews_remaining_batting,
                "drs_reviews_remaining_bowling": reviews_remaining_bowling,
                "review_taken": delivery.review is not None,
                "review_outcome": (
                    delivery.review.decision if delivery.review else None
                ),
                "review_by": delivery.review.by if delivery.review else None,
                
                # Enricher-populated fields (left null)
                "venue_lat": None,
                "venue_lon": None,
                "temperature_c": None,
                "humidity_pct": None,
                "wind_speed_kmh": None,
                "wind_direction_deg": None,
                "precipitation_mm": None,
                "cloud_cover_pct": None,
                "dew_point_c": None,
                "dew_likely_score": None,
                "match_start_time_local": None,
                "sunrise_local": None,
                "sunset_local": None,
                "is_day_session": None,
                "is_night_session": None,
                "is_twilight": None,
                "venue_capacity": None,
                "crowd_attendance": None,
                "crowd_noise_db": None,
                "pitch_report_text": None,
                "pitch_report_features": None,
                "pitch_type": None,
                "bowler_style": None,
                "bowler_pace_category": None,
                "bowler_arm": None,
                "bowler_spin_type": None,
                "boundary_length_short_m": None,
                "boundary_length_long_m": None,
                "boundary_straight_m": None,
                "shot_played": None,
                "shot_zone": None,
                "field_positions": None,
            }
            rows.append(row)
            
            # POST-STATE UPDATES: now apply this ball's effects
            innings_runs += delivery.runs.total
            if wicket["is_wicket"]:
                innings_wickets += 1
            
            # Batter stats: bat runs go to striker; balls faced by striker
            # only on legal balls and not byes/legbyes (those don't count
            # as the batter facing in the strict sense, but commonly we
            # count them as balls faced — Cricsheet convention; we count
            # any legal ball as a ball faced by the striker).
            batter_runs[striker] = batter_runs.get(striker, 0) + delivery.runs.batter
            if legal_ball:
                batter_balls[striker] = batter_balls.get(striker, 0) + 1
            
            # Bowler stats: runs conceded includes everything except byes
            # and legbyes (those aren't the bowler's fault).
            bowler_charge = (
                delivery.runs.batter + (wides or 0) + (noballs or 0) + (penalty or 0)
            )
            bowler_runs_conceded[bowler] = (
                bowler_runs_conceded.get(bowler, 0) + bowler_charge
            )
            if legal_ball:
                bowler_balls_bowled[bowler] = bowler_balls_bowled.get(bowler, 0) + 1
            # Bowler is credited with wickets only for certain dismissal kinds
            if wicket["is_wicket"] and wicket["wicket_kind"] in {
                "caught", "bowled", "lbw", "stumped", "caught and bowled",
                "hit wicket",
            }:
                bowler_wickets[bowler] = bowler_wickets.get(bowler, 0) + 1
            if bowler not in bowlers_seen_in_order:
                bowlers_seen_in_order.append(bowler)
            
            # Partnership: runs scored on the delivery count toward the
            # partnership; balls faced increments on legal balls; partnership
            # resets on wicket.
            partnership_runs += delivery.runs.total
            if legal_ball:
                partnership_balls += 1
            if wicket["is_wicket"]:
                partnership_runs = 0
                partnership_balls = 0
            
            # Phase counters
            if legal_ball:
                balls_into_phase += 1
            
            # Within-over state
            over_runs_so_far += delivery.runs.total
            if legal_ball:
                over_legal_balls_so_far += 1
                legal_balls_bowled += 1
            
            # Last-ball memory for the NEXT ball
            last_ball_was_dot = (delivery.runs.total == 0) and not wicket["is_wicket"]
            last_ball_was_boundary = delivery.runs.batter in (4, 6)
            last_ball_was_wicket = wicket["is_wicket"]
            
            is_first_ball_of_over = False
        
        # End of over: bank the over's totals for "last over" features
        runs_in_last_over = sum(d.runs.total for d in over.deliveries)
        wickets_in_last_over = sum(
            1 for d in over.deliveries if d.wickets
        )
        # Increment phase-overs counter at end of over
        overs_into_phase += 1
    
    # Post-pass: mark is_last_ball_of_over correctly. The last *legal*
    # ball of an over is the one we want flagged. We walk backwards within
    # each over and set the first legal ball we find.
    _mark_last_legal_ball_of_over(rows)
    
    return rows


def _mark_last_legal_ball_of_over(rows: list[dict[str, Any]]) -> None:
    """Set is_last_ball_of_over=True on the final legal ball of each over.
    Mutates rows in place."""
    # Group by (innings_idx, over_idx), find the last legal ball in each.
    current_key: tuple[int, int] | None = None
    current_group_indices: list[int] = []
    
    def flush(group_indices: list[int]) -> None:
        if not group_indices:
            return
        # Walk from the end, find first legal ball.
        for idx in reversed(group_indices):
            if rows[idx]["is_legal_ball"]:
                rows[idx]["is_last_ball_of_over"] = True
                return
    
    for i, row in enumerate(rows):
        key = (row["innings_idx"], row["over_idx"])
        if key != current_key:
            flush(current_group_indices)
            current_key = key
            current_group_indices = []
        current_group_indices.append(i)
    flush(current_group_indices)