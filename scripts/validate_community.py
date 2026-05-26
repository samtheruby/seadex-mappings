#!/usr/bin/env python3
"""Validate community/*.json files. Exits non-zero on any error.

Each file must be a JSON array of objects. Each object must have:
  - `filename` (non-empty string)
  - at least one of: `nyaa_link`, `nekobt_link`, `tosho_link`, `info_hash`

Optional fields are accepted but type-checked when present.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REQUIRED_FILENAME = "filename"
LINK_FIELDS = ("nyaa_link", "nekobt_link", "tosho_link", "info_hash")

STR_FIELDS = (
    "filename", "nyaa_id", "info_hash", "nekobt_link", "tosho_link",
    "nyaa_link", "nyaa_download_link", "release_group",
    "tmdb_type", "tmdb_tvdb_name", "romaji_name", "processed_at",
)
INT_FIELDS = ("tvdb_id", "tvdb_season", "tmdb_id")


def validate_obj(path: str, idx: int, obj: dict) -> list[str]:
    errs: list[str] = []
    where = f"{path}[{idx}]"

    if not isinstance(obj, dict):
        return [f"{where}: not a JSON object"]

    fname = obj.get(REQUIRED_FILENAME)
    if not isinstance(fname, str) or not fname.strip():
        errs.append(f"{where}: missing or empty `filename`")

    if not any(obj.get(k) for k in LINK_FIELDS):
        errs.append(
            f"{where}: must have at least one of: {', '.join(LINK_FIELDS)}"
        )

    for k in STR_FIELDS:
        if k in obj and obj[k] is not None and not isinstance(obj[k], str):
            errs.append(f"{where}: `{k}` must be a string")

    for k in INT_FIELDS:
        if k in obj and obj[k] is not None and not isinstance(obj[k], int):
            errs.append(f"{where}: `{k}` must be an integer")

    return errs


def validate_file(path: Path) -> list[str]:
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return [f"{path}: invalid JSON ({e})"]

    if not isinstance(data, list):
        return [f"{path}: top-level must be a JSON array"]

    errs: list[str] = []
    for i, obj in enumerate(data):
        errs.extend(validate_obj(str(path), i, obj))
    return errs


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: validate_community.py FILE [FILE ...]", file=sys.stderr)
        return 2

    all_errs: list[str] = []
    for f in argv:
        all_errs.extend(validate_file(Path(f)))

    if all_errs:
        for e in all_errs:
            print(e, file=sys.stderr)
        print(f"\n{len(all_errs)} error(s)", file=sys.stderr)
        return 1

    print(f"OK: {len(argv)} file(s) valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
