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