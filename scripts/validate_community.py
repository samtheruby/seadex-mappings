#!/usr/bin/env python3
"""Validate community/*.json files. Exits non-zero on any error.

Each file must be a JSON array of objects. Each object must have:
  - filename, tmdb_tvdb_name, release_group (non-empty strings)
  - at least one of: nyaa_link, nekobt_link
  - tmdb_type of 'movie' or 'show'
  - tvdb_id + tvdb_season (shows) OR tmdb_id (movies)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REQUIRED_STR = ("filename", "tmdb_tvdb_name", "release_group", "tmdb_type", "processed_at")
LINK_FIELDS = ("nyaa_link", "nekobt_link")
VALID_TMDB_TYPES = ("movie", "show")
VALID_RESOLUTIONS = ("480p", "720p", "1080p", "2160p")
VALID_RELEASE_TYPES = ("BluRay", "WEB-DL", "Remux", "DVD")
VALID_VIDEO_CODECS = ("x264", "x265", "H.264", "H.265", "AVC", "HEVC", "AV1")
VALID_AUDIO_CODECS = ("FLAC", "AAC", "Opus", "AC3", "EAC3", "DTS", "TrueHD", "PCM", "MP3", "Vorbis")

STR_FIELDS = (
    "filename", "tmdb_tvdb_name", "release_group", "tmdb_type", "processed_at",
    "nyaa_link", "nyaa_download_link", "nekobt_link",
)
INT_FIELDS = ("tvdb_id", "tvdb_season", "tmdb_id")

_SEASON_RE = re.compile(r"\.S\d{2}\.")
_YEAR_RE = re.compile(r"\.(?:19|20)\d{2}\.")
_GROUP_UNSAFE_RE = re.compile(r"""[<>:"/\\|?*'`\-]""")


def _sanitize_group(group: str) -> str:
    """Mirror sanitize_release_group from namer.rs."""
    s = _GROUP_UNSAFE_RE.sub("", group)
    return re.sub(r"\s+", "", s).strip(".")


def validate_filename(filename: str, tmdb_type: str, release_group: str) -> list[str]:
    errs = []

    if " " in filename:
        errs.append("filename must use dots as separators, not spaces")
    if ".." in filename:
        errs.append("filename contains consecutive dots")

    # Wrap with dots for cleaner boundary matching (year, season checks)
    padded = f".{filename}."

    if tmdb_type == "show" and not _SEASON_RE.search(padded):
        errs.append("TV filename must contain a season tag (e.g. .S01.)")

    if not _YEAR_RE.search(padded):
        errs.append("filename must contain a year (e.g. 2023)")

    if not any(res in filename for res in VALID_RESOLUTIONS):
        errs.append(f"filename must contain a resolution ({', '.join(VALID_RESOLUTIONS)})")

    if not any(rt in filename for rt in VALID_RELEASE_TYPES):
        errs.append(f"filename must contain a release type ({', '.join(VALID_RELEASE_TYPES)})")

    if not any(vc in filename for vc in VALID_VIDEO_CODECS):
        errs.append(f"filename must contain a video codec ({', '.join(VALID_VIDEO_CODECS)})")

    if not any(ac in filename for ac in VALID_AUDIO_CODECS):
        errs.append(f"filename must contain an audio codec ({', '.join(VALID_AUDIO_CODECS)})")

    expected_suffix = f"-{_sanitize_group(release_group)}"
    if not filename.endswith(expected_suffix):
        errs.append(f"filename must end with `{expected_suffix}` to match the release group")

    return errs


def validate_obj(path: str, idx: int, obj: dict) -> list[str]:
    errs: list[str] = []
    where = f"{path}[{idx}]"

    if not isinstance(obj, dict):
        return [f"{where}: not a JSON object"]

    for field in REQUIRED_STR:
        val = obj.get(field)
        if not isinstance(val, str) or not val.strip():
            errs.append(f"{where}: missing or empty `{field}`")

    if isinstance(filename, str) and filename.strip() and isinstance(release_group, str) and release_group.strip():
        errs.extend(validate_filename(filename, tmdb_type, release_group))

    if not any(obj.get(k) for k in LINK_FIELDS):
        errs.append(f"{where}: must have at least one of: {', '.join(LINK_FIELDS)}")

    filename = obj.get("filename", "")
    release_group = obj.get("release_group", "")
    tmdb_type = obj.get("tmdb_type", "")
    if tmdb_type not in VALID_TMDB_TYPES:
        errs.append(f"{where}: `tmdb_type` must be one of {VALID_TMDB_TYPES}, got {tmdb_type!r}")
    elif tmdb_type == "show":
        if not isinstance(obj.get("tvdb_id"), int):
            errs.append(f"{where}: show entries require integer `tvdb_id`")
        if not isinstance(obj.get("tvdb_season"), int):
            errs.append(f"{where}: show entries require integer `tvdb_season`")
    elif tmdb_type == "movie":
        if not isinstance(obj.get("tmdb_id"), int):
            errs.append(f"{where}: movie entries require integer `tmdb_id`")

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
