"""Cricsheet bulk data downloader with provenance tracking.

Downloads the all-matches JSON archive from cricsheet.org, records
provenance metadata (download timestamp, file hash, source URL, byte
size), and extracts the zip to a date-stamped directory.

The provenance file is the foundation of reproducibility: any paper
result we produce can be traced back to the exact data snapshot used.
"""

from __future__ import annotations

import hashlib
import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from tqdm import tqdm

import requests

from sillypoint.config import CRICSHEET_ALL_JSON_URL, CRICSHEET_DIR

logger = logging.getLogger(__name__)


def _compute_sha256(file_path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Compute the SHA-256 hash of a file by streaming.

    We stream rather than read the whole file into memory because the
    Cricsheet archive is ~200MB; reading it all at once works but is
    wasteful. SHA-256 is the standard cryptographic hash for content
    addressing — same bytes always give the same hash.

    Args:
        file_path: Path to the file to hash.
        chunk_size: Bytes to read per iteration. 1MB is a sensible default.

    Returns:
        Hex-encoded SHA-256 digest, 64 characters long.
    """
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        while chunk := f.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def download_cricsheet(
    url: str = CRICSHEET_ALL_JSON_URL,
    target_root: Path = CRICSHEET_DIR,
) -> Path:
    """Download the Cricsheet all-matches JSON archive.

    Creates a date-stamped subdirectory under target_root, downloads the
    zip into it, extracts the JSON files, and writes a provenance.json
    capturing exactly what was downloaded, from where, and when.

    Args:
        url: The Cricsheet download URL. Defaults to the all-matches JSON.
        target_root: The root directory under which to create the snapshot.

    Returns:
        Path to the date-stamped snapshot directory containing the
        extracted JSON files and provenance.json.
    """
    # Date-stamp the snapshot. We use UTC to avoid timezone ambiguity
    # in the historical record. Format: 2026-05-23.
    timestamp = datetime.now(timezone.utc)
    snapshot_name = timestamp.strftime("%Y-%m-%d")
    snapshot_dir = target_root / snapshot_name
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    zip_path = snapshot_dir / "all_json.zip"
    extract_dir = snapshot_dir / "matches"
    extract_dir.mkdir(exist_ok=True)

    # Step 1: Download with streaming so we don't load 200MB into memory.
    logger.info("Downloading %s -> %s", url, zip_path)
    chunk_size = 1024 * 1024  # 1 MiB
    with requests.get(url, stream=True, timeout=60) as response:
        response.raise_for_status()
        total_bytes = int(response.headers.get("Content-Length", 0))
        with zip_path.open("wb") as f, tqdm(
            total=total_bytes,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc="Cricsheet",
        ) as progress:
            for chunk in response.iter_content(chunk_size=chunk_size):
                f.write(chunk)
                progress.update(len(chunk))

    # Step 2: Verify what we got and capture provenance.
    file_size_bytes = zip_path.stat().st_size
    file_sha256 = _compute_sha256(zip_path)
    logger.info("Downloaded %d bytes, sha256=%s", file_size_bytes, file_sha256)

    # Step 3: Extract the zip into a dedicated subdirectory.
    logger.info("Extracting to %s", extract_dir)
    with zipfile.ZipFile(zip_path) as zf:
        member_names = zf.namelist()
        zf.extractall(extract_dir)
    logger.info("Extracted %d files", len(member_names))

    # Step 4: Write provenance.json. This file is the source of truth
    # for any future question about "where did this data come from?"
    provenance = {
        "source_url": url,
        "downloaded_at_utc": timestamp.isoformat(),
        "snapshot_dir": str(snapshot_dir),
        "zip_path": str(zip_path),
        "zip_size_bytes": file_size_bytes,
        "zip_sha256": file_sha256,
        "extracted_file_count": len(member_names),
        "cricsheet_license": "CC BY 3.0",
        "cricsheet_attribution": "Data sourced from Cricsheet (https://cricsheet.org)",
    }
    provenance_path = snapshot_dir / "provenance.json"
    with provenance_path.open("w") as f:
        json.dump(provenance, f, indent=2)
    logger.info("Wrote provenance to %s", provenance_path)

    return snapshot_dir


if __name__ == "__main__":
    # Configure logging so we see progress when running this as a script.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    snapshot_dir = download_cricsheet()
    print(f"\nSnapshot ready at: {snapshot_dir}")