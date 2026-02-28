from __future__ import annotations

import copy
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


ASSET_CACHE_ROOT = Path("output/instagram/assets_cache")
REQUEST_TIMEOUT_SEC = 20
SPORTMONKS_BASE_URL = "https://api.sportmonks.com/v3/football"


@dataclass(frozen=True)
class AssetCacheReport:
    player_requested: int
    team_requested: int
    player_cached: int
    team_cached: int
    downloads: int
    failures: int

    def as_dict(self) -> dict[str, int]:
        return {
            "player_requested": self.player_requested,
            "team_requested": self.team_requested,
            "player_cached": self.player_cached,
            "team_cached": self.team_cached,
            "downloads": self.downloads,
            "failures": self.failures,
        }


def enrich_manifest_with_cached_assets(
    manifest: dict[str, Any],
    *,
    cache_root: Path = ASSET_CACHE_ROOT,
) -> tuple[dict[str, Any], AssetCacheReport]:
    """Return manifest copy with local face/badge asset URIs attached to rows."""
    manifest_copy = copy.deepcopy(manifest)

    row_refs = _collect_row_refs(manifest_copy)
    if not row_refs:
        return (
            manifest_copy,
            AssetCacheReport(
                player_requested=0,
                team_requested=0,
                player_cached=0,
                team_cached=0,
                downloads=0,
                failures=0,
            ),
        )

    player_ids = sorted(
        {
            int(row.get("player_id"))
            for rows in row_refs.values()
            for row in rows
            if row.get("player_id") is not None
        }
    )
    team_ids = sorted(
        {
            int(row.get("team_id"))
            for rows in row_refs.values()
            for row in rows
            if row.get("team_id") is not None
        }
    )

    from src import data_fetcher  # lazy import so env loading from posting settings happens first

    players = data_fetcher.get_players_by_ids(player_ids) if player_ids else {}
    teams = data_fetcher.get_teams_by_ids(team_ids) if team_ids else {}

    session = requests.Session()
    sportmonks_token = os.getenv("SPORTMONKS_API_TOKEN")

    downloads = 0
    failures = 0
    player_cached = 0
    team_cached = 0

    player_assets: dict[int, dict[str, str]] = {}
    for player_id in player_ids:
        row = players.get(player_id) or {}
        source_url = _normalize_image_url(row.get("image_path"))
        if not source_url and sportmonks_token:
            source_url = _sportmonks_image_path(session, "players", player_id, sportmonks_token)
        local_path = None
        if source_url:
            try:
                local_path, did_download = _ensure_cached_image(
                    session,
                    source_url,
                    cache_root / "players",
                    str(player_id),
                )
                downloads += int(did_download)
            except Exception:
                failures += 1
                local_path = None
        if local_path and local_path.exists():
            player_cached += 1
            player_assets[player_id] = {
                "url": source_url or "",
                "path": str(local_path),
                "uri": local_path.resolve().as_uri(),
            }

    team_assets: dict[int, dict[str, str]] = {}
    for team_id in team_ids:
        row = teams.get(team_id) or {}
        source_url = _normalize_image_url(row.get("image_path"))
        if not source_url and sportmonks_token:
            source_url = _sportmonks_image_path(session, "teams", team_id, sportmonks_token)
        local_path = None
        if source_url:
            try:
                local_path, did_download = _ensure_cached_image(
                    session,
                    source_url,
                    cache_root / "teams",
                    str(team_id),
                )
                downloads += int(did_download)
            except Exception:
                failures += 1
                local_path = None
        if local_path and local_path.exists():
            team_cached += 1
            team_assets[team_id] = {
                "url": source_url or "",
                "path": str(local_path),
                "uri": local_path.resolve().as_uri(),
            }

    for row_id, rows in row_refs.items():
        if not rows:
            continue
        exemplar = rows[0]
        pid = exemplar.get("player_id")
        tid = exemplar.get("team_id")
        for row in rows:
            assets = dict(row.get("assets") or {})
            if pid is not None and int(pid) in player_assets:
                pdata = player_assets[int(pid)]
                assets["player_face_url"] = pdata["url"]
                assets["player_face_path"] = pdata["path"]
                assets["player_face_uri"] = pdata["uri"]
            if tid is not None and int(tid) in team_assets:
                tdata = team_assets[int(tid)]
                assets["team_badge_url"] = tdata["url"]
                assets["team_badge_path"] = tdata["path"]
                assets["team_badge_uri"] = tdata["uri"]
            if assets:
                row["assets"] = assets

    def _attach_team_assets(team_payload: dict[str, Any] | None) -> None:
        if not isinstance(team_payload, dict):
            return
        team_id = team_payload.get("team_id")
        if team_id is None:
            return
        tdata = team_assets.get(int(team_id))
        if not tdata:
            return
        team_payload["badge_url"] = tdata["url"]
        team_payload["badge_path"] = tdata["path"]
        team_payload["badge_uri"] = tdata["uri"]

    for slide in list(manifest_copy.get("slides") or []):
        _attach_team_assets(slide.get("home_team"))
        _attach_team_assets(slide.get("away_team"))

    for fixture in list(((manifest_copy.get("fixtures") or {}).get("items") or [])):
        _attach_team_assets(fixture.get("home_team"))
        _attach_team_assets(fixture.get("away_team"))

    report = AssetCacheReport(
        player_requested=len(player_ids),
        team_requested=len(team_ids),
        player_cached=player_cached,
        team_cached=team_cached,
        downloads=downloads,
        failures=failures,
    )
    manifest_copy["asset_cache"] = report.as_dict()
    return manifest_copy, report


def _collect_row_refs(manifest: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    refs: dict[str, list[dict[str, Any]]] = {}

    def _append_rows(rows: list[dict[str, Any]] | None) -> None:
        for row in rows or []:
            row_id = str(row.get("id") or "")
            if row_id:
                refs.setdefault(row_id, []).append(row)

    sections = ((manifest.get("sections") or {}).get("by_section") or {})
    for rows in sections.values():
        _append_rows(list(rows or []))

    for slide in list(manifest.get("slides") or []):
        slide_type = slide.get("slide_type")
        if slide_type in {"section", "fixture"}:
            _append_rows(list(slide.get("rows") or []))
            continue
        if slide_type == "fixture_rich":
            for section in list(slide.get("sections") or []):
                _append_rows(list((section or {}).get("rows") or []))

    for fixture in list(((manifest.get("fixtures") or {}).get("items") or [])):
        _append_rows(list(fixture.get("rows") or []))
        for section in list(fixture.get("sections") or []):
            _append_rows(list((section or {}).get("rows") or []))
    return refs


def _normalize_image_url(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.startswith("//"):
        return "https:" + text
    if text.startswith("http://") or text.startswith("https://"):
        return text
    return None


def _safe_ext_for_url(url: str) -> str:
    path = urlparse(url).path or ""
    suffix = Path(path).suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        return suffix
    return ".png"


def _ensure_cached_image(
    session: requests.Session,
    source_url: str,
    cache_dir: Path,
    base_name: str,
) -> tuple[Path, bool]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    ext = _safe_ext_for_url(source_url)
    dest = cache_dir / f"{base_name}{ext}"
    if dest.exists() and dest.stat().st_size > 0:
        return dest, False

    resp = session.get(source_url, timeout=REQUEST_TIMEOUT_SEC)
    resp.raise_for_status()
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(resp.content)
    if tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(f"Downloaded empty image from {source_url}")
    tmp.replace(dest)
    return dest, True


def _sportmonks_image_path(
    session: requests.Session,
    entity: str,
    entity_id: int,
    token: str,
) -> str | None:
    # Best-effort fallback for missing DB image_path values.
    url = f"{SPORTMONKS_BASE_URL}/{entity}/{entity_id}"
    try:
        resp = session.get(url, params={"api_token": token}, timeout=REQUEST_TIMEOUT_SEC)
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        return None

    data = payload.get("data")
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, dict):
        return None

    for key in ("image_path", "logo_path", "logo"):
        value = _normalize_image_url(data.get(key))
        if value:
            return value
    return None
