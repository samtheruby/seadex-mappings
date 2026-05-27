#!/usr/bin/env python3
"""Build seadex.db and community.db from text source-of-truth.

Inputs:
  seadex/ledger.ndjson    — append-only, last-write-wins by seadex_torrent_id,
                            entries with dropped=true are excluded.
  community/*.json        — arrays of release objects, one file per show.

Outputs (in cwd):
  seadex.db               — `releases` table consumed by seadex-indexer.
  community.db            — `community_releases` table consumed by seadex-indexer.
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER = REPO_ROOT / "seadex" / "ledger.ndjson"
COMMUNITY_DIR = REPO_ROOT / "community"
SEADEX_DB = REPO_ROOT / "seadex.db"
COMMUNITY_DB = REPO_ROOT / "community.db"

RELEASES_SCHEMA = """
CREATE TABLE releases (
    seadex_torrent_id TEXT PRIMARY KEY,
    al_id             INTEGER,
    filename          TEXT,
    seadex_anime_name TEXT,
    nyaa_link         TEXT,
    nyaa_download_link TEXT,
    info_hash         TEXT,
    release_group     TEXT,
    tvdb_id           INTEGER,
    tvdb_season       INTEGER,
    tmdb_id           INTEGER,
    tmdb_type         TEXT,
    tmdb_tvdb_name    TEXT,
    romaji_name       TEXT,
    release_type      TEXT,
    resolution        TEXT,
    video_codec       TEXT,
    audio_codec       TEXT,
    bit_depth         TEXT,
    hdr               TEXT,
    incomplete        INTEGER DEFAULT 0,
    dual_audio        INTEGER DEFAULT 0,
    processed_at      TEXT
);
CREATE INDEX idx_releases_tvdb     ON releases(tvdb_id, tvdb_season);
CREATE INDEX idx_releases_tmdb     ON releases(tmdb_id, tmdb_type);
CREATE INDEX idx_releases_proc     ON releases(processed_at DESC);
"""

COMMUNITY_SCHEMA = """
CREATE TABLE community_releases (
    rowid             INTEGER PRIMARY KEY AUTOINCREMENT,
    nekobt_link       TEXT,
    filename          TEXT,
    nyaa_link         TEXT,
    nyaa_download_link TEXT,
    release_group     TEXT,
    tvdb_id           INTEGER,
    tvdb_season       INTEGER,
    tmdb_id           INTEGER,
    tmdb_type         TEXT,
    tmdb_tvdb_name    TEXT,
    processed_at      TEXT
);
CREATE INDEX idx_community_tvdb ON community_releases(tvdb_id, tvdb_season);
CREATE INDEX idx_community_tmdb ON community_releases(tmdb_id, tmdb_type);
CREATE INDEX idx_community_proc ON community_releases(processed_at DESC);
"""

RELEASES_COLUMNS = [
    "seadex_torrent_id", "al_id", "filename", "seadex_anime_name",
    "nyaa_link", "nyaa_download_link", "info_hash", "release_group",
    "tvdb_id", "tvdb_season", "tmdb_id", "tmdb_type",
    "tmdb_tvdb_name", "romaji_name",
    "release_type", "resolution", "video_codec", "audio_codec",
    "bit_depth", "hdr",
    "incomplete", "dual_audio",
    "processed_at",
]

COMMUNITY_COLUMNS = [
    "nekobt_link",
    "filename", "nyaa_link", "nyaa_download_link", "release_group",
    "tvdb_id", "tvdb_season", "tmdb_id", "tmdb_type",
    "tmdb_tvdb_name", "processed_at",
]


def load_ledger() -> list[dict]:
    """Read ledger.ndjson, apply last-write-wins, drop tombstones."""
    if not LEDGER.exists():
        print(f"warn: {LEDGER} not found — building empty seadex.db")
        return []

    by_id: dict[str, dict] = {}
    bad = 0
    with LEDGER.open() as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as e:
                bad += 1
                print(f"warn: ledger.ndjson:{lineno}: bad JSON ({e})", file=sys.stderr)
                continue
            tid = entry.get("seadex_torrent_id")
            if not tid:
                bad += 1
                print(f"warn: ledger.ndjson:{lineno}: missing seadex_torrent_id", file=sys.stderr)
                continue
            by_id[tid] = entry

    live = [e for e in by_id.values() if not e.get("dropped")]
    dropped = len(by_id) - len(live)
    print(f"ledger: {len(by_id)} unique entries ({dropped} dropped, {bad} bad lines)")
    return live


def load_community() -> list[dict]:
    """Read all community/*.json files (each an array)."""
    if not COMMUNITY_DIR.exists():
        return []

    out: list[dict] = []
    for path in sorted(COMMUNITY_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as e:
            print(f"warn: {path.name}: bad JSON ({e}) — skipping", file=sys.stderr)
            continue
        if not isinstance(data, list):
            print(f"warn: {path.name}: top-level not an array — skipping", file=sys.stderr)
            continue
        for i, obj in enumerate(data):
            if not isinstance(obj, dict):
                print(f"warn: {path.name}[{i}]: not an object — skipping", file=sys.stderr)
                continue
            out.append(obj)
    print(f"community: {out and len(out) or 0} releases across {len(list(COMMUNITY_DIR.glob('*.json')))} files")
    return out


_NYAA_ID_RE = re.compile(r"/view/(\d+)")

def derive_nyaa_fields(obj: dict) -> dict:
    """Fill nyaa_download_link from nyaa_link if not already set."""
    nyaa_link = obj.get("nyaa_link", "")
    if not nyaa_link:
        return obj
    m = _NYAA_ID_RE.search(nyaa_link)
    if not m:
        return obj
    nyaa_id = m.group(1)
    if not obj.get("nyaa_download_link"):
        out = dict(obj)
        out["nyaa_download_link"] = f"https://nyaa.si/download/{nyaa_id}.torrent"
        return out
    return obj


def coerce_bool(v) -> int:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(bool(v))
    if isinstance(v, str):
        return int(v.lower() in ("true", "1", "yes"))
    return 0


def build_seadex_db(entries: list[dict]) -> None:
    SEADEX_DB.unlink(missing_ok=True)
    conn = sqlite3.connect(SEADEX_DB)
    try:
        conn.executescript(RELEASES_SCHEMA)
        rows = []
        for e in entries:
            rows.append((
                e.get("seadex_torrent_id"),
                e.get("al_id"),
                e.get("filename"),
                e.get("seadex_anime_name"),
                e.get("nyaa_link"),
                e.get("nyaa_download_link"),
                e.get("info_hash"),
                e.get("release_group"),
                e.get("tvdb_id"),
                e.get("tvdb_season"),
                e.get("tmdb_id"),
                e.get("tmdb_type"),
                e.get("tmdb_tvdb_name"),
                e.get("romaji_name"),
                e.get("release_type"),
                e.get("resolution"),
                e.get("video_codec"),
                e.get("audio_codec"),
                e.get("bit_depth"),
                e.get("hdr"),
                coerce_bool(e.get("incomplete")),
                coerce_bool(e.get("dual_audio")),
                e.get("timestamp"),
            ))
        placeholders = ",".join(["?"] * len(RELEASES_COLUMNS))
        conn.executemany(
            f"INSERT INTO releases ({','.join(RELEASES_COLUMNS)}) VALUES ({placeholders})",
            rows,
        )
        conn.commit()
        print(f"seadex.db: {len(rows)} rows")
    finally:
        conn.close()


def build_community_db(entries: list[dict]) -> None:
    COMMUNITY_DB.unlink(missing_ok=True)
    conn = sqlite3.connect(COMMUNITY_DB)
    try:
        conn.executescript(COMMUNITY_SCHEMA)
        rows = []
        for e in entries:
            e = derive_nyaa_fields(e)
            rows.append(tuple(e.get(col) for col in COMMUNITY_COLUMNS))
        placeholders = ",".join(["?"] * len(COMMUNITY_COLUMNS))
        conn.executemany(
            f"INSERT INTO community_releases ({','.join(COMMUNITY_COLUMNS)}) VALUES ({placeholders})",
            rows,
        )
        conn.commit()
        print(f"community.db: {len(rows)} rows")
    finally:
        conn.close()


def main() -> int:
    build_seadex_db(load_ledger())
    build_community_db(load_community())
    return 0


if __name__ == "__main__":
    sys.exit(main())
