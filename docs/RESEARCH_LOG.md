# Sillypoint Research Log

This file is the daily diary of the project. Every working session adds at least one entry. The purpose is reproducibility: six months from now, when writing the paper, every decision, data version, hyperparameter choice, and dead-end attempted needs to be recoverable from this file.

**Format for each entry:**
- Date (YYYY-MM-DD)
- What I did
- What I decided (and why)
- Open questions / what's next

**Rules:**
- Append-only. Past entries are never edited (except for typo fixes). If a past decision turned out wrong, write a new entry explaining the reversal.
- Be concrete. "Trained a model" is useless; "Trained LightGBM win-prob model on Cricsheet matches < 2024-01-01, validated on 2024 matches, Brier score 0.187" is useful.
- Link to commits, files, and external references where relevant.

---

## 2026-05-23 — Project initiated

**What I did:**
- Set up local development environment on WSL2 Ubuntu 26.04 with Python 3.14.4.
- Created the `sillypoint` project directory and Python virtual environment.
- Initialized git repository (branch: `main`).
- Created project skeleton with directories: `docs/`, `data/`, `sillypoint/`, `notebooks/`, `tests/`, `scripts/`, `eval/`.

**What I decided:**
- **Paper direction: A + B.** Foundation model (CrickFormer) for ball-by-ball cricket events + agentic natural-language interface as the deployed system.
  - Rationale: CricBench (Devraj et al., BITS Pilani, Dec 2025) closes the standalone cricket text-to-SQL benchmark gap. Pressure index closed-form formulas (Shah 2014, Mallawa Arachchi 2024, Bandyopadhyay 2025) are well-trodden. A learned representation for cricket event sequences is open, paralleling baller2vec (basketball) and ScoutGPT (football, 2026).
- **Naming:** Project = `sillypoint`. Domain = `sillypoint.dev` (TBD).
- **Hosting plan:** Hetzner CX22 (€4.51/mo) for backend + Vercel free tier for frontend. Frontend not provisioned yet.
- **Data source posture:** Cricsheet for historical (CC BY 3.0), grey-zone scraping of Cricbuzz/ESPNcricinfo for live data. Acknowledged commercial ceiling.
- **Reproducibility commitments:**
  - Strict temporal train/test splits — no random splits, ever.
  - MLflow tracking from the first model run.
  - Version-pin Cricsheet downloads (record download date + file hash).
  - Append-only research log (this file).

**Open questions / next:**
- Confirm Cricsheet download timestamp and bulk-download strategy.
- Decide on Hetzner provisioning date.
- Domain registration: `sillypoint.dev` availability check.
- First model in MLflow: probably a LightGBM win-probability baseline (Month 2).

---
## 2026-05-23 — Cricsheet ingestion: data acquired, schema designed

**What I did:**
- Implemented `sillypoint/ingestion/cricsheet.py` — downloader with provenance tracking (SHA-256 hash, download timestamp, file count) writing to `data/raw/cricsheet/<date>/`.
- Downloaded the all-matches archive: 21,801 matches, 96.1 MB compressed → 3.3 GB extracted JSON. SHA-256 `63861209a8ed963020e99857a67b934925e011b1c670465ec70d59ed6abfa9ab`. This is the canonical snapshot for the paper.
- Explored Cricsheet JSON structure hands-on: `meta` / `info` / `innings`. Innings → overs → deliveries nesting. Player registry maps short names ("PJ Cummins") to UUIDs ("ded9240e") — critical for disambiguation.
- Picked canonical exploration match: 1529292, SRH vs PBKS, 2026-05-06, Hyderabad. SRH 235, PBKS chased to 202, SRH won by 33 runs. POM: Pat Cummins (captain, bowling).

**What I decided:**
- **Two-layer data model.** Layer 1: Pydantic models faithful to Cricsheet JSON (fail-loud on schema drift). Layer 2: flat per-delivery table written to Parquet, ~70 denormalized columns. One Parquet per match initially; combined file materialized later for queries.
- **Delivery ID:** composite string `{match_id}-{innings_idx}-{over_idx}-{delivery_idx_in_over}`, plus all four components as separate columns. `delivery_idx_in_over` is the raw Cricsheet array position (always unique even with extras); `legal_ball_in_over` is a separate 1-6 counter for legal balls only.
- **Indexing convention:** all integers 0-indexed in the data layer (matches Cricsheet source). UI/display layer adds 1 where human-friendly. Eliminates whole class of off-by-one bugs.
- **Player identity:** UUID as canonical join key (`batter_id` from `registry.people`). Short name (`batter`) denormalized alongside for human readability. Separate `players` table for `short_name` → `display_name` mapping (e.g., "PJ Cummins" → "Pat Cummins", populated later).
- **Maximum denormalization for state.** Every delivery row stores pre-state including: innings runs/wickets/balls, striker and non-striker runs/balls, partnership state, bowler state, chase context (target/runs-to-win/RRR for innings 1), phase tag, recent-momentum signals (last_ball_was_*, runs/wickets in last over). Storage cost acceptable in Parquet; query simplicity gain large.
- **Phase column:** clean categorical `powerplay`/`middle`/`death`/`normal` based on fielding restrictions. NOT subdivided (kept clean for ML one-hot encoding). Nuance captured via additional columns: `balls_into_phase`, `overs_into_phase`, `is_phase_transition`. Separate `test_session` and `test_day` for Test matches, populated later.
- **Enrichments (separate from parser, populated by enricher workers in later months):**
  - Month 2: weather via Open-Meteo (free, no key, historical back to 2021 via ERA5 reanalysis archive). Geocode venue names via Nominatim. Compute dew-likelihood from temp + humidity (Magnus formula). Day/night via `astral` library + per-tournament default start times.
  - Month 4: Cricinfo scraping for pitch report text (raw + LLM-extracted features), crowd attendance from news sources, structured bowler attributes (style/arm/pace category/spin type) from Cricinfo player profiles. Shot zone from commentary text.
  - Static venue data hand-curated: capacity, boundary dimensions (short/long/straight in meters) for major venues.
- **Deferred / not committed:**
  - `crowd_noise_db` — column exists, nullable, no commitment to populate.
  - Video-derived bowler biomechanics — deferred indefinitely. Reasoning: CrickFormer learns bowler tendencies implicitly via UUID embeddings; explicit biomechanics features not required for the foundation-model paper. Possible follow-up paper later.
  - Shot type from video (CV pipeline) — deferred indefinitely; shot zone partially obtainable from Cricinfo commentary text instead.

**Open questions / next:**
- Write `sillypoint/ingestion/schema.py` (Pydantic Layer 1) and `sillypoint/ingestion/parser.py` (transformation to Layer 2). Verify SRH innings parses to 235 runs.
- Then: scale parser to all 21,801 matches, write one Parquet per match into `data/processed/cricsheet/<date>/`.
- After that: materialize combined Parquet for DuckDB queries.

---
## 2026-05-23 (continued) — Schema locked

**What I did:**
- Wrote Pydantic schema (`sillypoint/ingestion/schema.py`, Layer 1) mirroring Cricsheet JSON.
- Wrote breadth test (`scripts/test_schema_breadth.py`): parses one representative match per format.
- Wrote random sample test (`scripts/test_schema_random.py`): parses 100 random matches with seed=42.
- Result: 10/10 formats clean, 100/100 random sample clean.

**What I decided:**
- **Schema relaxations, each justified by observed data:**
  - `Replacements` is a `{match: [...], role: [...]}` object (not flat list) — IPL impact-player rule, discovered on match 1529292.
  - `info.season` accepts `str | int` — older Tests use bare int (`2011`), modern data uses `"2024/25"`.
  - `event.group` accepts `str | int` — domestic competitions have both alphabetic ("A") and numeric (`1`) groups.
  - `Fielder.name` optional — Cricsheet records fielding involvement without identity for some unnamed substitutes / incomplete domestic scoring.
- **Schema versioning policy:** every relaxation gets a code comment explaining why. No preemptive loosening to `Any`.
- **Reproducibility lock:** random test uses seed=42 always, so anyone re-running confirms the same 100 matches passed.

**Open questions / next:**
- Write `sillypoint/ingestion/parser.py` — transform validated Pydantic Match into the flat ~70-column delivery table for analytics.
- Verify SRH match 1529292 parses to 235 first-innings runs *via the parser*, not just by summing Pydantic models.
- Then scale to all 21,800 matches, one Parquet per match.

---
## 2026-05-23 (continued) — Full snapshot parsed, all 21,800 matches in Parquet

**What I did:**
- Implemented `DELIVERY_SCHEMA` in `sillypoint/ingestion/parser.py` — explicit Polars schema for ~90 columns, prevents type-inference flakiness on columns that are early-null (DRS reviews, wickets, list fields).
- Implemented `scripts/parse_all_matches.py` — idempotent batch parser with progress bar and failures log.
- Parsed all 21,800 matches: 21,791 succeeded initially.

**What I decided:**
- **Innings with no overs are valid data.** Discovered via 9 initial failures: forfeited / abandoned / rained-off innings. Most striking example: match 1160280, Central Stags vs Canterbury 2018, where both teams mutually forfeited their middle innings to engineer a contrived finish after rain washed out the first 2 days. Relaxed `Innings.overs` to `Field(default_factory=list)`.
- **Empty rows from a match are also valid** — entirely abandoned matches produce zero rows. Removed the "fail if 0 rows" check; we write empty Parquets so downstream code knows the match existed.
- **Schema in code, not inferred.** Explicit `DELIVERY_SCHEMA` is now the canonical specification. Any new column added to the parser must also be added here.

**Open questions / next:**
- Materialize combined Parquet for the full snapshot (one file with ~4M rows).
- Load into DuckDB for first-class SQL queries.
- Run sanity queries: total deliveries, per-format ball counts, top run-scorers all-time.
- Verify the materialized Parquet matches per-match Parquets by row count and key sums.

---