#!/usr/bin/env python3
"""Process a community-release GitHub issue into a community/*.json entry.

Reads from env vars (set by the workflow):
  ISSUE_NUMBER, ISSUE_BODY

Outputs:
  Writes/updates community/tvdb-{id}.json or community/tmdb-{id}.json
  Writes /tmp/community_result.txt for the workflow to post as a comment.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMUNITY_DIR = REPO_ROOT / "community"
RESULT_FILE = Path("/tmp/community_result.txt")

NYAA_URL = "https://nyaa.si/view/{id}"
NYAA_DOWNLOAD_URL = "https://nyaa.si/download/{id}.torrent"
NEKOBT_URL = "https://nekobt.to/torrents/{id}"


def parse_issue_body(body: str) -> dict[str, str]:
    """Parse GitHub issue form body (### Heading / value format) into a flat dict."""
    result: dict[str, str] = {}
    for section in re.split(r"^### ", body, flags=re.MULTILINE):
        if not section.strip():
            continue
        lines = section.strip().splitlines()
        key = lines[0].strip().lower().replace(" ", "_")
        value = "\n".join(lines[1:]).strip()
        if value and value != "_No response_":
            result[key] = value
    return result


def load_community_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def upsert_entry(entries: list[dict], new_entry: dict, link_key: str, link_value: str) -> tuple[list[dict], bool]:
    """Insert or replace by link URL. Returns (updated_list, was_updated)."""
    for i, e in enumerate(entries):
        if e.get(link_key) == link_value:
            entries[i] = new_entry
            return entries, True
    entries.append(new_entry)
    return entries, False


def _fail(msg: str) -> None:
    RESULT_FILE.write_text(f"❌ {msg}")
    print(f"error: {msg}", file=sys.stderr)


def main() -> int:
    body = os.environ.get("ISSUE_BODY", "")
    if not body:
        _fail("Issue body is empty.")
        return 1

    fields = parse_issue_body(body)
    print(f"Parsed fields: {list(fields.keys())}", file=sys.stderr)

    # Tracker + ID → URL
    tracker = fields.get("tracker", "").strip()
    torrent_id = fields.get("torrent_id", "").strip()

    if not torrent_id or not torrent_id.isdigit():
        _fail(f"Invalid torrent ID: {torrent_id!r}")
        return 1

    if tracker == "Nyaa":
        nyaa_link = NYAA_URL.format(id=torrent_id)
        nyaa_download_link = NYAA_DOWNLOAD_URL.format(id=torrent_id)
        nekobt_link = None
        link_key, link_value = "nyaa_link", nyaa_link
    elif tracker == "NekoBT":
        nyaa_link = None
        nyaa_download_link = None
        nekobt_link = NEKOBT_URL.format(id=torrent_id)
        link_key, link_value = "nekobt_link", nekobt_link
    else:
        _fail(f"Unknown tracker: {tracker!r}")
        return 1

    # User-supplied metadata
    filename = fields.get("filename", "").strip()
    tmdb_tvdb_name = fields.get("tmdb_tvdb_name", "").strip() or fields.get("show_name", "").strip() or fields.get("movie_name", "").strip()
    release_group = fields.get("release_group", "").strip()

    if not filename:
        _fail("Filename is required.")
        return 1
    if not tmdb_tvdb_name:
        _fail("Show/movie name is required.")
        return 1
    if not release_group:
        _fail("Release group is required.")
        return 1

    # Determine movie vs TV by which ID fields are present
    tvdb_id_raw = fields.get("tvdb_id", "").strip()
    tmdb_id_raw = fields.get("tmdb_id", "").strip()
    tvdb_season_raw = fields.get("tvdb_season", "1").strip()

    is_movie = bool(tmdb_id_raw) and not bool(tvdb_id_raw)

    if not is_movie and not tvdb_id_raw:
        _fail("TV release requires a TVDB ID.")
        return 1
    if is_movie and not tmdb_id_raw:
        _fail("Movie release requires a TMDB ID.")
        return 1

    entry: dict = {
        "filename": filename,
        "tmdb_tvdb_name": tmdb_tvdb_name,
        "release_group": release_group,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

    if nyaa_link:
        entry["nyaa_link"] = nyaa_link
    if nyaa_download_link:
        entry["nyaa_download_link"] = nyaa_download_link
    if nekobt_link:
        entry["nekobt_link"] = nekobt_link

    if is_movie:
        entry["tmdb_id"] = int(tmdb_id_raw)
        entry["tmdb_type"] = "movie"
        file_key = f"tmdb-{tmdb_id_raw}"
    else:
        tvdb_season = int(tvdb_season_raw) if tvdb_season_raw.isdigit() else 1
        entry["tvdb_id"] = int(tvdb_id_raw)
        entry["tvdb_season"] = tvdb_season
        entry["tmdb_type"] = "show"
        file_key = f"tvdb-{tvdb_id_raw}"

    COMMUNITY_DIR.mkdir(exist_ok=True)
    out_path = COMMUNITY_DIR / f"{file_key}.json"
    entries = load_community_file(out_path)
    entries, updated = upsert_entry(entries, entry, link_key, link_value)
    out_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")

    action = "Updated" if updated else "Added"
    result_msg = (
        f"✅ **{action}** `{filename}`\n\n"
        f"- File: `community/{file_key}.json`\n"
        f"- Tracker: {tracker} ({torrent_id})\n"
        f"- Name: {tmdb_tvdb_name}\n"
        f"- Group: {release_group}\n"
    )
    RESULT_FILE.write_text(result_msg)
    print(result_msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
