#!/usr/bin/env python3
"""Process a community-release GitHub issue into a community/*.json entry.

Reads from env vars (set by the workflow):
  ISSUE_NUMBER, ISSUE_BODY, TVDB_API_KEY (optional), TMDB_API_KEY (optional)

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

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
COMMUNITY_DIR = REPO_ROOT / "community"
RESULT_FILE = Path("/tmp/community_result.txt")

# ---- Issue body parser ----

def parse_issue_body(body: str) -> dict[str, str]:
    """Parse GitHub issue form body into a flat dict keyed by field heading."""
    result: dict[str, str] = {}
    sections = re.split(r"^### ", body, flags=re.MULTILINE)
    for section in sections:
        if not section.strip():
            continue
        lines = section.strip().splitlines()
        key = lines[0].strip().lower().replace(" ", "_")
        value = "\n".join(lines[1:]).strip()
        if value and value != "_No response_":
            result[key] = value
    return result


# ---- Nyaa metadata ----

_NYAA_ID_RE = re.compile(r"/view/(\d+)")
_INFOHASH_RE = re.compile(r"urn:btih:([0-9a-fA-F]{40})", re.IGNORECASE)
_B32_INFOHASH_RE = re.compile(r"urn:btih:([A-Z2-7]{32})", re.IGNORECASE)

def _b32_to_hex(s: str) -> str | None:
    ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ234567"
    s = s.upper()
    bits = 0
    num_bits = 0
    output = []
    for ch in s:
        val = ALPHA.find(ch)
        if val == -1:
            return None
        bits = (bits << 5) | val
        num_bits += 5
        if num_bits >= 8:
            num_bits -= 8
            output.append((bits >> num_bits) & 0xFF)
    if len(output) == 20:
        return "".join(f"{b:02x}" for b in output)
    return None


def fetch_nyaa_metadata(nyaa_link: str) -> dict:
    """Fetch title and infohash from a Nyaa view page."""
    result = {"nyaa_id": None, "title": None, "info_hash": None,
              "nyaa_download_link": None}

    m = _NYAA_ID_RE.search(nyaa_link)
    if not m:
        return result
    nyaa_id = m.group(1)
    result["nyaa_id"] = nyaa_id
    result["nyaa_download_link"] = f"https://nyaa.si/download/{nyaa_id}.torrent"

    try:
        resp = httpx.get(nyaa_link, timeout=20, follow_redirects=True,
                         headers={"User-Agent": "seadex-community-bot/1.0"})
        resp.raise_for_status()
        html = resp.text

        title_m = re.search(r"<title>([^<]+)\|", html)
        if title_m:
            result["title"] = title_m.group(1).strip()

        hash_m = _INFOHASH_RE.search(html)
        if hash_m:
            result["info_hash"] = hash_m.group(1).lower()
        else:
            b32_m = _B32_INFOHASH_RE.search(html)
            if b32_m:
                result["info_hash"] = _b32_to_hex(b32_m.group(1))
    except Exception as e:
        print(f"warn: Nyaa fetch failed: {e}", file=sys.stderr)

    return result


# ---- Quality parsers (mirrors processor.rs) ----

def parse_resolution(title: str) -> str | None:
    t = title.lower()
    if "2160p" in t or "4k" in t:
        return "2160p"
    if "1080p" in t:
        return "1080p"
    if "720p" in t:
        return "720p"
    if "480p" in t:
        return "480p"
    return None


def parse_video_codec(title: str) -> str | None:
    t = title.lower()
    if any(x in t for x in ("h.265", "h265", "x265", "hevc")):
        return "HEVC"
    if any(x in t for x in ("h.264", "h264", "x264", "avc")):
        return "AVC"
    if "av1" in t:
        return "AV1"
    return None


_WEB_RE = re.compile(r"\bweb\b")

def infer_release_type(title: str) -> str:
    t = title.lower()
    if "remux" in t:
        return "Remux"
    if "web-dl" in t or "webdl" in t or "webrip" in t or _WEB_RE.search(t):
        return "WEB-DL"
    if "dvd" in t:
        return "DVD"
    return "BluRay"


_GROUP_RE = re.compile(r"^\[([^\]]+)\]\s*")

def parse_release_group(title: str) -> str | None:
    m = _GROUP_RE.match(title.strip())
    if m:
        return m.group(1).strip() or None
    # try trailing -Group pattern
    m2 = re.search(r"-([A-Za-z0-9_]+)(?:\.[a-z]{2,4})?$", title)
    if m2:
        return m2.group(1)
    return None


# ---- Filename generator (mirrors namer.rs) ----

_SEP_RE = re.compile(r"[/&+~]")
_UNSAFE_RE = re.compile(r"""[<>:"/\\|?*'`]""")
_MULTIDOT_RE = re.compile(r"\.{2,}")
_WHITESPACE_RE = re.compile(r"\s+")
_GROUP_UNSAFE_RE = re.compile(r"""[<>:"/\\|?*'`]""")


def sanitize_title(title: str) -> str:
    s = _SEP_RE.sub(".", title)
    s = _UNSAFE_RE.sub("", s)
    s = s.replace(" ", ".")
    s = _MULTIDOT_RE.sub(".", s)
    return s.strip(".")


def sanitize_group(group: str) -> str:
    s = _GROUP_UNSAFE_RE.sub("", group)
    s = s.replace("-", "")
    s = _WHITESPACE_RE.sub("", s)
    return s.strip(".")


def map_video_codec(codec: str, release_type: str) -> str:
    upper = codec.upper()
    is_avc = upper in ("AVC", "H.264", "H264", "X264")
    is_hevc = upper in ("HEVC", "H.265", "H265", "X265")
    if release_type == "Remux":
        if is_avc: return "AVC"
        if is_hevc: return "HEVC"
    elif release_type == "WEB-DL":
        if is_avc: return "H.264"
        if is_hevc: return "H.265"
    else:
        if is_avc: return "x264"
        if is_hevc: return "x265"
    return codec


def generate_filename(
    name: str,
    is_movie: bool,
    season: int | None,
    year: int | None,
    resolution: str | None,
    release_type: str | None,
    video_codec: str | None,
    dual_audio: bool,
    incomplete: bool,
    release_group: str | None,
) -> str:
    parts = [sanitize_title(name)]
    if not is_movie:
        parts.append(f"S{(season or 1):02d}")
    if year:
        parts.append(str(year))
    if incomplete:
        parts.append("INCOMPLETE")
    if resolution:
        parts.append(resolution)
    rt = release_type or "BluRay"
    if release_type:
        parts.append(rt)
    if dual_audio:
        parts.append("Dual-Audio")
    if video_codec:
        parts.append(map_video_codec(video_codec, rt))
    filename = ".".join(parts)
    if release_group:
        sg = sanitize_group(release_group)
        if sg:
            filename += f"-{sg}"
    return filename


# ---- External metadata lookups ----

async def _noop(): pass  # placeholder


def tvdb_login(api_key: str) -> str | None:
    try:
        resp = httpx.post(
            "https://api4.thetvdb.com/v4/login",
            json={"apikey": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["data"]["token"]
    except Exception as e:
        print(f"warn: TVDB login failed: {e}", file=sys.stderr)
        return None


def tvdb_get_series(token: str, tvdb_id: int) -> dict | None:
    try:
        resp = httpx.get(
            f"https://api4.thetvdb.com/v4/series/{tvdb_id}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json().get("data", {})
        name = data.get("name")
        year = None
        first_aired = data.get("firstAired", "")
        if first_aired and len(first_aired) >= 4:
            try:
                year = int(first_aired[:4])
            except ValueError:
                pass
        return {"name": name, "year": year}
    except Exception as e:
        print(f"warn: TVDB series lookup failed: {e}", file=sys.stderr)
        return None


def tmdb_get_movie(api_key: str, tmdb_id: int) -> dict | None:
    try:
        resp = httpx.get(
            f"https://api.themoviedb.org/3/movie/{tmdb_id}",
            params={"api_key": api_key},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        name = data.get("title")
        year = None
        rd = data.get("release_date", "")
        if rd and len(rd) >= 4:
            try:
                year = int(rd[:4])
            except ValueError:
                pass
        return {"name": name, "year": year}
    except Exception as e:
        print(f"warn: TMDB movie lookup failed: {e}", file=sys.stderr)
        return None


# ---- Community JSON read/write ----

def load_community_file(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def upsert_entry(entries: list[dict], new_entry: dict, nyaa_id: str | None) -> tuple[list[dict], bool]:
    """Insert or replace by nyaa_id. Returns (updated_list, was_updated)."""
    if nyaa_id:
        for i, e in enumerate(entries):
            if e.get("nyaa_id") == nyaa_id:
                entries[i] = new_entry
                return entries, True
    entries.append(new_entry)
    return entries, False


# ---- Main ----

def main() -> int:
    issue_number = os.environ.get("ISSUE_NUMBER", "?")
    body = os.environ.get("ISSUE_BODY", "")
    tvdb_api_key = os.environ.get("TVDB_API_KEY", "")
    tmdb_api_key = os.environ.get("TMDB_API_KEY", "")

    if not body:
        _fail("Issue body is empty.")
        return 1

    fields = parse_issue_body(body)
    print(f"Parsed fields: {list(fields.keys())}", file=sys.stderr)

    release_type_raw = fields.get("release_type", "tv_show").lower()
    is_movie = "movie" in release_type_raw

    nyaa_link = fields.get("nyaa_link", "").strip()
    if not nyaa_link:
        _fail("No Nyaa link provided.")
        return 1

    tvdb_id_raw = fields.get("tvdb_id", "").strip()
    tmdb_id_raw = fields.get("tmdb_id", "").strip()
    season_raw = fields.get("season_number", fields.get("season", "1")).strip()
    flags_raw = fields.get("flags", "")
    dual_audio = "dual audio" in flags_raw.lower()
    incomplete = "incomplete" in flags_raw.lower()

    tvdb_id = int(tvdb_id_raw) if tvdb_id_raw.isdigit() else None
    tmdb_id = int(tmdb_id_raw) if tmdb_id_raw.isdigit() else None
    season = int(season_raw) if season_raw.isdigit() else 1

    if not is_movie and not tvdb_id:
        _fail("TV Show requires a TVDB ID.")
        return 1
    if is_movie and not tmdb_id:
        _fail("Movie requires a TMDB ID.")
        return 1

    # Fetch Nyaa metadata
    nyaa = fetch_nyaa_metadata(nyaa_link)
    nyaa_title = nyaa.get("title") or ""
    print(f"Nyaa title: {nyaa_title!r}", file=sys.stderr)

    # Parse quality signals from Nyaa title
    resolution = parse_resolution(nyaa_title)
    video_codec = parse_video_codec(nyaa_title)
    release_type = infer_release_type(nyaa_title)
    release_group = parse_release_group(nyaa_title)

    # Resolve show metadata
    tmdb_tvdb_name: str | None = None
    year: int | None = None

    if not is_movie and tvdb_id and tvdb_api_key:
        token = tvdb_login(tvdb_api_key)
        if token:
            info = tvdb_get_series(token, tvdb_id)
            if info:
                tmdb_tvdb_name = info.get("name")
                year = info.get("year")

    if is_movie and tmdb_id and tmdb_api_key:
        info = tmdb_get_movie(tmdb_api_key, tmdb_id)
        if info:
            tmdb_tvdb_name = info.get("name")
            year = info.get("year")

    if not tmdb_tvdb_name:
        print("warn: could not resolve show name from API — filename will use 'Unknown'", file=sys.stderr)

    filename = generate_filename(
        name=tmdb_tvdb_name or "Unknown",
        is_movie=is_movie,
        season=season if not is_movie else None,
        year=year,
        resolution=resolution,
        release_type=release_type,
        video_codec=video_codec,
        dual_audio=dual_audio,
        incomplete=incomplete,
        release_group=release_group,
    )

    entry: dict = {
        "filename": filename,
        "nyaa_link": nyaa_link,
        "nyaa_id": nyaa.get("nyaa_id"),
        "nyaa_download_link": nyaa.get("nyaa_download_link"),
        "info_hash": nyaa.get("info_hash"),
        "release_group": release_group,
        "tmdb_tvdb_name": tmdb_tvdb_name,
        "romaji_name": None,
        "processed_at": datetime.now(timezone.utc).isoformat(),
    }

    if is_movie:
        entry["tmdb_id"] = tmdb_id
        entry["tmdb_type"] = "movie"
        file_key = f"tmdb-{tmdb_id}"
    else:
        entry["tvdb_id"] = tvdb_id
        entry["tvdb_season"] = season
        entry["tmdb_type"] = "show"
        file_key = f"tvdb-{tvdb_id}"

    # Remove None values to keep JSON clean
    entry = {k: v for k, v in entry.items() if v is not None}

    COMMUNITY_DIR.mkdir(exist_ok=True)
    out_path = COMMUNITY_DIR / f"{file_key}.json"
    entries = load_community_file(out_path)
    entries, updated = upsert_entry(entries, entry, nyaa.get("nyaa_id"))
    out_path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n")

    action = "Updated" if updated else "Added"
    result_msg = (
        f"✅ **{action}** `{filename}`\n\n"
        f"- File: `community/{file_key}.json`\n"
        f"- Nyaa: {nyaa_link}\n"
        f"- Resolution: {resolution or 'unknown'}, Codec: {video_codec or 'unknown'}, "
        f"Type: {release_type}\n"
    )
    if not tmdb_api_key and not tvdb_api_key:
        result_msg += "\n> ⚠️ No API keys configured — show name could not be resolved automatically.\n"

    RESULT_FILE.write_text(result_msg)
    print(result_msg)
    return 0


def _fail(msg: str) -> None:
    RESULT_FILE.write_text(f"❌ {msg}")
    print(f"error: {msg}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
