"""Project-wide configuration."""

from __future__ import annotations

from pathlib import Path

# Project root: this file is at sillypoint/config.py, so the project root
# is two parents up (../..).
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# Data directories. All data lives under data/, organized by lifecycle stage.
DATA_DIR: Path = PROJECT_ROOT / "data"
RAW_DIR: Path = DATA_DIR / "raw"
PROCESSED_DIR: Path = DATA_DIR / "processed"

# We store each download in a date-stamped subdirectory to preserve historical snapshots of the data.
CRICSHEET_DIR: Path = RAW_DIR / "cricsheet"

# Cricsheet bulk download URL for all matches as JSON.
# Source: https://cricsheet.org/downloads/
CRICSHEET_ALL_JSON_URL: str = "https://cricsheet.org/downloads/all_json.zip"