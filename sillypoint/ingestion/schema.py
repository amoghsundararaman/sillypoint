"""Pydantic models for Cricsheet JSON (Layer 1 of the data model).

These models mirror the on-disk structure of Cricsheet match files
exactly. They serve two purposes:

1. Validation — if Cricsheet ever changes their format, parsing fails
   loud with a clear error message instead of silently producing wrong
   numbers downstream.
2. Documentation — the schema *is* the specification of what we expect.
   Reviewers and future maintainers read this file to understand the data.

Cricsheet's published format reference:
    https://cricsheet.org/format/json/

The flat per-delivery analytics schema (Layer 2) lives in parser.py.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ----------------------------------------------------------------------------
# Configuration: forbid unexpected fields so schema drift is loud.
# ----------------------------------------------------------------------------

class CricsheetModel(BaseModel):
    """Base class for all Cricsheet schema models.
    
    `extra="allow"` means: if Cricsheet adds a new field, we don't crash —
    we accept it but ignore it. Combined with explicit logging in the
    parser, this is the right balance: known fields are strictly validated,
    unknown fields are quietly tolerated until we choose to handle them.
    """
    model_config = ConfigDict(extra="allow")


# ----------------------------------------------------------------------------
# Meta block: file-level metadata about the JSON itself (not the match).
# ----------------------------------------------------------------------------

class Meta(CricsheetModel):
    """Top-level `meta` block in each Cricsheet match file."""
    data_version: str
    created: date
    revision: int


# ----------------------------------------------------------------------------
# Event: tournament context (IPL, World Cup, bilateral series, etc.).
# Many matches have an event; some bilateral fixtures don't.
# ----------------------------------------------------------------------------

class Event(CricsheetModel):
    """Tournament or series context for the match."""
    name: str | None = None
    match_number: int | None = None
    stage: str | None = None  # e.g. "Final", "Eliminator"
    group: str | int | None = None
    sub_name: str | None = None


# ----------------------------------------------------------------------------
# Outcome: result of the match. Several shapes possible.
# ----------------------------------------------------------------------------

class OutcomeBy(CricsheetModel):
    """How the winning team won: by runs (defended), by wickets (chased),
    or by innings (Tests). Exactly one of these is populated when there's
    a definite winner; all are None for ties/no-results/draws."""
    runs: int | None = None
    wickets: int | None = None
    innings: int | None = None


class Outcome(CricsheetModel):
    """Match result. Three mutually-exclusive shapes:
    
    1. Definite winner: `winner` set, `by` populated, `result` None.
    2. No winner: `result` set to "tie" | "no result" | "draw",
       `winner` and `by` both None.
    3. Bowl-out / super over decided: `winner` set, `method` set to
       describe how (e.g. "D/L"), `by` may or may not be populated.
    """
    winner: str | None = None
    by: OutcomeBy | None = None
    result: str | None = None  # "tie" | "no result" | "draw"
    method: str | None = None  # "D/L" | "VJD" | "Eliminator" etc.
    bowl_out: str | None = None  # winner of a bowl-out tiebreaker
    eliminator: str | None = None


# ----------------------------------------------------------------------------
# Toss: who won, what they chose.
# ----------------------------------------------------------------------------

class Toss(CricsheetModel):
    """Toss winner and their decision."""
    winner: str
    decision: str  # "bat" | "field"
    uncontested: bool | None = None  # rare: toss not held


# ----------------------------------------------------------------------------
# Officials: umpires, match referees, TV umpires, reserve umpires.
# ----------------------------------------------------------------------------

class Officials(CricsheetModel):
    """Match officials. All lists are optional; minor matches often lack
    full official records."""
    umpires: list[str] | None = None
    tv_umpires: list[str] | None = None
    reserve_umpires: list[str] | None = None
    match_referees: list[str] | None = None


# ----------------------------------------------------------------------------
# Registry: the player name → UUID lookup. This is critical.
# ----------------------------------------------------------------------------

class Registry(CricsheetModel):
    """Maps every short name used in this match to a stable player UUID.
    The UUID is consistent across all Cricsheet matches: PJ Cummins is
    always 'ded9240e' regardless of which match we're in."""
    people: dict[str, str] = Field(
        ...,
        description="Short name (e.g. 'PJ Cummins') → UUID hex string."
    )


# ----------------------------------------------------------------------------
# Powerplay specification (limited-overs only).
# ----------------------------------------------------------------------------

class Powerplay(CricsheetModel):
    """A powerplay range in limited-overs cricket. Cricsheet expresses
    over numbers in fractional 0-indexed form: 0.1 = first ball, 5.6 =
    last ball of over 5."""
    from_: float = Field(..., alias="from")
    to: float
    type: str  # "mandatory" | "batting" | "bowling"


# ----------------------------------------------------------------------------
# Match info: everything about the match except the ball-by-ball data.
# ----------------------------------------------------------------------------

class MatchInfo(CricsheetModel):
    """The `info` block. Roughly 15-20 fields describing the match
    context: who, where, when, what format, who won."""
    balls_per_over: int
    teams: list[str] = Field(..., min_length=2, max_length=2)
    dates: list[date] = Field(..., min_length=1)
    match_type: str  # "T20" | "ODI" | "Test" | "IT20" | "MDM" | "ODM" | "100"
    gender: str  # "male" | "female"
    
    # Optional/contextual fields
    venue: str | None = None
    city: str | None = None
    season: str | int | None = None
    team_type: str | None = None  # "international" | "club" etc.
    match_type_number: int | None = None
    overs: int | None = None  # overs per innings for limited-overs
    event: Event | None = None
    
    outcome: Outcome
    toss: Toss
    player_of_match: list[str] | None = None
    
    # Squad list per team
    players: dict[str, list[str]] = Field(
        ...,
        description="Team name → list of short names of playing XI."
    )
    
    # The crucial UUID registry
    registry: Registry
    
    # Optional ancillary records
    officials: Officials | None = None
    powerplays: list[Powerplay] | None = None
    miscounted_overs: dict[str, Any] | None = None
    supersubs: dict[str, str] | None = None
    bowl_out: list[dict[str, Any]] | None = None


# ----------------------------------------------------------------------------
# Delivery: a single ball. The atomic unit of cricket.
# ----------------------------------------------------------------------------

class Runs(CricsheetModel):
    """Runs scored off the delivery, broken down by attribution."""
    batter: int = Field(..., ge=0)
    extras: int = Field(..., ge=0)
    total: int = Field(..., ge=0)
    non_boundary: bool | None = None  # rare: a 6 hit off a no-ball etc.


class Extras(CricsheetModel):
    """Detailed breakdown of extras. Any combination of fields may be
    present; all are optional. A delivery with no extras omits this object
    entirely."""
    wides: int | None = None
    noballs: int | None = None
    byes: int | None = None
    legbyes: int | None = None
    penalty: int | None = None


class Fielder(CricsheetModel):
    """A fielder involved in a dismissal. Object form (not just a string)
    because fielders can be substitute, have associated metadata, etc.
    
    Name is optional because Cricsheet occasionally records a fielding
    involvement without a confirmed identity (e.g., unidentified substitutes,
    incomplete scorer records in older or minor matches)."""
    name: str | None = None
    substitute: bool | None = None


class Wicket(CricsheetModel):
    """A wicket falling. The outer `wickets` field in a delivery is a
    list because a single ball can rarely dismiss two batters."""
    kind: str  # "caught" | "bowled" | "lbw" | "run out" | "stumped" | ...
    player_out: str
    fielders: list[Fielder] | None = None  # absent for bowled, lbw, etc.


class Review(CricsheetModel):
    """A DRS review taken on this delivery."""
    by: str  # team that reviewed
    umpire: str | None = None
    batter: str | None = None
    decision: str | None = None  # "struck down" | "upheld" etc.
    type: str | None = None  # "lbw" | "caught" etc.


class ReplacementMatch(CricsheetModel):
    """A match-level replacement (impact player, etc.). Tied to a delivery
    via the outer Replacements wrapper on a Delivery."""
    in_: str = Field(..., alias="in")
    out: str | None = None
    reason: str | None = None  # e.g. "impact_player"
    team: str | None = None


class ReplacementRole(CricsheetModel):
    """A role-level replacement (concussion sub, super-sub, etc.)."""
    role: str | None = None  # the role being filled
    in_: str = Field(..., alias="in")
    out: str | None = None
    reason: str | None = None


class Replacements(CricsheetModel):
    """Wrapper for replacement events on a single delivery.
    
    Cricsheet groups replacements into 'match' (impact-player style,
    strategic) and 'role' (forced, like concussion subs). Either or both
    keys may be present."""
    match: list[ReplacementMatch] | None = None
    role: list[ReplacementRole] | None = None


class Delivery(CricsheetModel):
    """A single ball. The most-instantiated model in our system — there
    are roughly 4 million of these in the snapshot."""
    batter: str
    bowler: str
    non_striker: str
    runs: Runs
    extras: Extras | None = None
    wickets: list[Wicket] | None = None
    review: Review | None = None
    replacements: Replacements | None = None


# ----------------------------------------------------------------------------
# Over: a wrapper around a list of deliveries.
# ----------------------------------------------------------------------------

class Over(CricsheetModel):
    """One over. Note the 0-indexed `over` field — Cricsheet convention."""
    over: int = Field(..., ge=0)
    deliveries: list[Delivery] = Field(..., min_length=1)


# ----------------------------------------------------------------------------
# Innings: a team batting through to its end.
# ----------------------------------------------------------------------------

class Innings(CricsheetModel):
    """One innings. Limited-overs matches have 2 innings (plus super
    overs as additional entries if applicable). Tests have up to 4."""
    team: str
    overs: list[Over] = Field(..., min_length=1)
    
    # Optional innings-level annotations
    powerplays: list[Powerplay] | None = None
    target: dict[str, Any] | None = None  # revised target after rain etc.
    super_over: bool | None = None
    forfeited: bool | None = None
    declared: bool | None = None
    absent_hurt: list[str] | None = None
    penalty_runs: dict[str, int] | None = None
    miscounted_overs: dict[str, Any] | None = None


# ----------------------------------------------------------------------------
# Match: the root model.
# ----------------------------------------------------------------------------

class Match(CricsheetModel):
    """A complete Cricsheet match file. This is the root model loaded
    from each JSON on disk."""
    meta: Meta
    info: MatchInfo
    innings: list[Innings] = Field(..., min_length=1)


# ----------------------------------------------------------------------------
# Convenience loader.
# ----------------------------------------------------------------------------

def load_match(json_path) -> Match:
    """Load and validate a single Cricsheet match file.
    
    Args:
        json_path: Path to a Cricsheet match JSON file (anything accepted
            by pathlib.Path).
    
    Returns:
        A validated Match object.
    
    Raises:
        pydantic.ValidationError: If the JSON doesn't conform to the schema.
        FileNotFoundError: If the path doesn't exist.
    """
    import json
    from pathlib import Path
    
    path = Path(json_path)
    with path.open() as f:
        raw = json.load(f)
    return Match.model_validate(raw)