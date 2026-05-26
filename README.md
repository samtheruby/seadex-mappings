# seadex-mappings

Source-of-truth data for the Seadex anime indexer pipeline.

## Layout

```
seadex/
  ledger.ndjson          # append-only, written by seadex-mapper bot
community/
  tvdb-<id>.json         # human-curated additions, array per show
scripts/
  build_db.py            # ledger + JSON  →  seadex.db + community.db
.github/workflows/
  build-db.yml           # rebuild + publish on push to main
  validate-community-pr.yml
```

## How it works

1. **seadex-mapper** (separate repo) polls Seadex, resolves metadata, and opens
   PRs adding new lines to `seadex/ledger.ndjson`.
2. Humans can submit PRs adding entries under `community/` for non-Seadex
   releases.
3. On merge to `main`, `build-db.yml` regenerates `seadex.db` + `community.db`
   and uploads them as assets on the rolling `db-latest` release.
4. **seadex-indexer** (separate repo) pulls those release assets and serves
   them via Torznab to Sonarr/Radarr.

## Ledger format

`seadex/ledger.ndjson` is append-only. Each line is a JSON object keyed by
`seadex_torrent_id`. Last write wins. Setting `dropped: true` tombstones an
entry — it stays in history but is excluded from the built DB.

## Community submissions

Each file under `community/` is a JSON array of release objects for one show
(filename convention: `tvdb-<tvdb_id>.json`, or any descriptive name —
filename is not parsed). See `validate-community-pr.yml` for required fields.

Minimum fields per object: `filename`, plus at least one of `nyaa_link`,
`nekobt_link`, `tosho_link`, or `info_hash`.

## Building locally

```sh
python3 scripts/build_db.py
# Produces ./seadex.db and ./community.db in the repo root.
```
