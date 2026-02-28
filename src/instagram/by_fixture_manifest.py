from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any


FIXTURE_HEADER_RE = re.compile(r"^(?P<teams>.+? vs .+?)\s+-\s+(?P<kickoff>.+)$")
LINE_RE = re.compile(r"^(?P<label>.+?)\s+\(won in (?P<wins>\d+)/(?P<total>\d+)\)$")
SHOTS_RE = re.compile(r"^(?P<subject>.+?)\s+(?P<market>(?:\d+\+\s+shots|(?:\d+\+\s+)?SOT))$", re.IGNORECASE)
FOULS_COMMITTED_RE = re.compile(
    r"^(?P<subject>.+?)\s+(?P<market>\d+\+\s+(?:foul committed|fouls committed))$",
    re.IGNORECASE,
)
FOULS_WON_RE = re.compile(
    r"^(?P<subject>.+?)\s+(?P<market>\d+\+\s+(?:foul won|fouls won))$",
    re.IGNORECASE,
)
CORNERS_RE = re.compile(r"^(?P<subject>.+?)\s+(?P<market>\d+\+\s+corners)$", re.IGNORECASE)

SECTION_ORDER = ["shots", "fouls_committed", "fouls_won", "corners"]
SECTION_META = {
    "shots": {"title": "Shots", "color": "#F5C518"},
    "fouls_committed": {"title": "Fouls Committed", "color": "#FF8C54"},
    "fouls_won": {"title": "Fouls Won", "color": "#54B0FF"},
    "corners": {"title": "Corners", "color": "#A78BFA"},
}
TEAM_ACCENTS = {
    "arsenal": "#EF0107",
    "aston villa": "#95BFE5",
    "bournemouth": "#DA291C",
    "brentford": "#D20000",
    "brighton": "#0057B8",
    "burnley": "#6C1D45",
    "chelsea": "#034694",
    "crystal palace": "#C4122E",
    "everton": "#003399",
    "fulham": "#F5F5F5",
    "leeds": "#FFCD00",
    "liverpool": "#C8102E",
    "man city": "#6CABDD",
    "man utd": "#DA291C",
    "newcastle": "#C5B358",
    "nottm forest": "#DD0000",
    "palace": "#C4122E",
    "spurs": "#FFFFFF",
    "sunderland": "#EB172B",
    "west ham": "#7A263A",
    "wolves": "#FDB913",
}


@dataclass(frozen=True)
class ParsedFixtureRow:
    label: str
    wins: int
    total: int


@dataclass(frozen=True)
class ParsedFixture:
    header: str
    home_display: str
    away_display: str
    kickoff: str
    rows: list[ParsedFixtureRow]


def _canonical_hash(value: Any) -> str:
    return __import__("hashlib").sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


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


def _shorten_player_name(name: str) -> str:
    clean = name.strip()
    if not clean:
        return clean
    parts = clean.split()
    if len(parts) >= 2:
        first = parts[0].replace(".", "")
        last = parts[-1]
        if first:
            return f"{first[0].upper()}. {last}"
    return clean


def _format_date_badge(scheduled_for: str) -> str:
    target = date.fromisoformat(scheduled_for)
    return target.strftime("%d %b %Y")


def _format_kickoff_label(raw: str) -> str:
    text = raw.strip().lower().replace(" ", "")
    match = re.match(r"^(?P<hour>\d{1,2}):(?P<minute>\d{2})(?P<meridiem>am|pm)$", text)
    if not match:
        return raw.strip()
    return f"{match.group('hour')}:{match.group('minute')} {match.group('meridiem').upper()}"


def _clean_team_display(value: str) -> str:
    text = value.strip()
    text = re.sub(r"^[^\w]+", "", text).strip()
    text = re.sub(r"[^\w]+$", "", text).strip()
    return text


def _team_accent(*names: str) -> str:
    for name in names:
        key = name.strip().lower()
        if key in TEAM_ACCENTS:
            return TEAM_ACCENTS[key]
    return "#F5C518"


def parse_by_fixture_text(content: str) -> tuple[str, list[str], list[ParsedFixture], list[str]]:
    lines = [line.rstrip() for line in content.splitlines()]
    header = ""
    intro: list[str] = []
    outro: list[str] = []
    fixtures: list[ParsedFixture] = []

    current_fixture: ParsedFixture | None = None
    current_rows: list[ParsedFixtureRow] = []
    seen_fixture = False

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        fixture_match = FIXTURE_HEADER_RE.match(line)
        if fixture_match:
            seen_fixture = True
            if current_fixture is not None:
                fixtures.append(
                    ParsedFixture(
                        header=current_fixture.header,
                        home_display=current_fixture.home_display,
                        away_display=current_fixture.away_display,
                        kickoff=current_fixture.kickoff,
                        rows=current_rows,
                    )
                )
            teams = fixture_match.group("teams")
            home_display, away_display = [_clean_team_display(part) for part in teams.split(" vs ", 1)]
            current_fixture = ParsedFixture(
                header=line,
                home_display=home_display,
                away_display=away_display,
                kickoff=fixture_match.group("kickoff").strip(),
                rows=[],
            )
            current_rows = []
            continue

        if not seen_fixture:
            if not header:
                header = line
            else:
                intro.append(line)
            continue

        row_match = LINE_RE.match(line)
        if row_match and current_fixture is not None:
            current_rows.append(
                ParsedFixtureRow(
                    label=row_match.group("label").strip(),
                    wins=int(row_match.group("wins")),
                    total=int(row_match.group("total")),
                )
            )
            continue

        if current_fixture is not None:
            fixtures.append(
                ParsedFixture(
                    header=current_fixture.header,
                    home_display=current_fixture.home_display,
                    away_display=current_fixture.away_display,
                    kickoff=current_fixture.kickoff,
                    rows=current_rows,
                )
            )
            current_fixture = None
            current_rows = []
        outro.append(line)

    if current_fixture is not None:
        fixtures.append(
            ParsedFixture(
                header=current_fixture.header,
                home_display=current_fixture.home_display,
                away_display=current_fixture.away_display,
                kickoff=current_fixture.kickoff,
                rows=current_rows,
            )
        )

    return header, intro, fixtures, outro


def _parse_row_label(label: str) -> tuple[str, str, str]:
    for section_key, regex in (
        ("shots", SHOTS_RE),
        ("fouls_committed", FOULS_COMMITTED_RE),
        ("fouls_won", FOULS_WON_RE),
        ("corners", CORNERS_RE),
    ):
        match = regex.match(label)
        if match:
            return section_key, match.group("subject").strip(), match.group("market").strip()
    return "other", label.strip(), ""


def _subject_market_display(
    *,
    section_key: str,
    subject: str,
    market: str,
    duplicate_subjects: set[str],
) -> tuple[str, str]:
    if section_key == "shots":
        normalized_market = market.strip()
        return subject, normalized_market

    if section_key in {"fouls_committed", "fouls_won"}:
        threshold_match = re.match(r"^(?P<threshold>\d+)\+", market)
        threshold = int(threshold_match.group("threshold")) if threshold_match else 1
        show_threshold = threshold != 1 or _normalize_name(subject) in duplicate_subjects
        return subject, f"{threshold}+" if show_threshold else ""

    if section_key == "corners":
        threshold_match = re.match(r"^(?P<threshold>\d+)\+", market)
        threshold = int(threshold_match.group("threshold")) if threshold_match else 0
        return subject, f"{threshold}+"

    return subject, market.strip()


def _density_for_total_rows(total_rows: int) -> str:
    if total_rows >= 25:
        return "xdense"
    if total_rows >= 19:
        return "dense"
    return "default"


def _team_name_variants(display_name: str, canonical_name: str) -> set[str]:
    return {
        _normalize_name(display_name),
        _normalize_name(canonical_name),
    }


def _player_name_candidates(row: dict[str, Any]) -> set[str]:
    candidates: set[str] = set()
    for key in ("display_name", "common_name", "short_name", "name"):
        value = str(row.get(key) or "").strip()
        if not value:
            continue
        candidates.add(_normalize_name(value))
        candidates.add(_normalize_name(_shorten_player_name(value)))
    return {candidate for candidate in candidates if candidate}


def _try_enrich_with_db(fixtures: list[dict[str, Any]], *, scheduled_for: str) -> None:
    if not os.getenv("SUPABASE_DB_URL"):
        return

    from src import data_fetcher, formatter

    target = date.fromisoformat(scheduled_for)
    actual_fixtures = data_fetcher.get_fixtures_for_day(target)
    if not actual_fixtures:
        return

    team_ids = sorted(
        {
            int(team_id)
            for fixture in actual_fixtures
            for team_id in (fixture.home_team_id, fixture.away_team_id)
        }
    )
    teams_by_id = data_fetcher.get_teams_by_ids(team_ids)

    actual_contexts: list[dict[str, Any]] = []
    for fixture in actual_fixtures:
        home_team = teams_by_id.get(int(fixture.home_team_id)) or {}
        away_team = teams_by_id.get(int(fixture.away_team_id)) or {}
        home_name = str(home_team.get("name") or f"Team {fixture.home_team_id}")
        away_name = str(away_team.get("name") or f"Team {fixture.away_team_id}")
        home_display = formatter.SHORT_TEAM_NAMES.get(home_name, home_name)
        away_display = formatter.SHORT_TEAM_NAMES.get(away_name, away_name)
        actual_contexts.append(
            {
                "fixture_id": int(fixture.id),
                "home_team_id": int(fixture.home_team_id),
                "away_team_id": int(fixture.away_team_id),
                "home_name": home_name,
                "away_name": away_name,
                "home_display": home_display,
                "away_display": away_display,
                "home_badge_url": _normalize_image_url(home_team.get("image_path")),
                "away_badge_url": _normalize_image_url(away_team.get("image_path")),
            }
        )

    player_maps_by_team: dict[int, dict[str, dict[str, Any]]] = {}

    def build_player_map(team_id: int) -> dict[str, dict[str, Any]]:
        cached = player_maps_by_team.get(team_id)
        if cached is not None:
            return cached
        fixtures_for_team = data_fetcher.get_recent_team_fixtures(team_id, limit=1)
        if not fixtures_for_team:
            player_maps_by_team[team_id] = {}
            return {}
        last_fixture_id = fixtures_for_team[0].id
        starter_rows = data_fetcher.get_fixture_players([last_fixture_id], team_id)
        player_ids = [
            int(row["player_id"])
            for row in starter_rows
            if row.get("player_id") is not None and row.get("is_starter")
        ]
        if not player_ids:
            player_ids = [int(row["player_id"]) for row in starter_rows if row.get("player_id") is not None]
        players = data_fetcher.get_players_by_ids(player_ids)
        mapped: dict[str, dict[str, Any]] = {}
        for player_id in player_ids:
            player = players.get(player_id)
            if not player:
                continue
            payload = {
                "player_id": int(player_id),
                "team_id": int(team_id),
                "team_name": str((teams_by_id.get(team_id) or {}).get("name") or ""),
                "player_display": _shorten_player_name(
                    str(
                        player.get("display_name")
                        or player.get("common_name")
                        or player.get("short_name")
                        or player.get("name")
                        or ""
                    )
                ),
                "player_face_url": _normalize_image_url(player.get("image_path")),
                "team_badge_url": _normalize_image_url((teams_by_id.get(team_id) or {}).get("image_path")),
            }
            for candidate in _player_name_candidates(player):
                mapped.setdefault(candidate, payload)
        player_maps_by_team[team_id] = mapped
        return mapped

    for fixture in fixtures:
        fixture_key = (
            _normalize_name(str(fixture.get("home_display") or "")),
            _normalize_name(str(fixture.get("away_display") or "")),
        )
        match = next(
            (
                context
                for context in actual_contexts
                if (
                    _normalize_name(context["home_display"]),
                    _normalize_name(context["away_display"]),
                )
                == fixture_key
            ),
            None,
        )
        if match is None:
            continue

        fixture["fixture_id"] = match["fixture_id"]
        fixture["home_team"] = {
            "team_id": match["home_team_id"],
            "name": match["home_name"],
            "display_name": match["home_display"],
            "badge_url": match["home_badge_url"],
            "accent_color": _team_accent(match["home_display"], match["home_name"]),
        }
        fixture["away_team"] = {
            "team_id": match["away_team_id"],
            "name": match["away_name"],
            "display_name": match["away_display"],
            "badge_url": match["away_badge_url"],
            "accent_color": _team_accent(match["away_display"], match["away_name"]),
        }

        team_variants = {
            **{
                variant: fixture["home_team"]
                for variant in _team_name_variants(match["home_display"], match["home_name"])
            },
            **{
                variant: fixture["away_team"]
                for variant in _team_name_variants(match["away_display"], match["away_name"])
            },
        }
        home_players = build_player_map(match["home_team_id"])
        away_players = build_player_map(match["away_team_id"])
        player_lookup = {**away_players, **home_players}

        for section in list(fixture.get("sections") or []):
            for row in list(section.get("rows") or []):
                subject_key = _normalize_name(str(row.get("subject_name") or ""))
                if row.get("subject_type") == "team":
                    team_info = team_variants.get(subject_key)
                    if team_info:
                        row["team_id"] = team_info["team_id"]
                        row["team_name"] = team_info["name"]
                        row["assets"] = {
                            **dict(row.get("assets") or {}),
                            "team_badge_url": team_info["badge_url"] or "",
                        }
                    continue

                player_info = player_lookup.get(subject_key)
                if not player_info:
                    continue
                row["player_id"] = player_info["player_id"]
                row["team_id"] = player_info["team_id"]
                row["team_name"] = player_info["team_name"]
                row["subject_display"] = row.get("subject_display") or player_info["player_display"]
                row["assets"] = {
                    **dict(row.get("assets") or {}),
                    "player_face_url": player_info["player_face_url"] or "",
                    "team_badge_url": player_info["team_badge_url"] or "",
                }


def verify_by_fixture_manifest(manifest: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    slides = list(manifest.get("slides") or [])
    if not slides:
        return ["manifest has no slides"]

    fixture_items = list(((manifest.get("fixtures") or {}).get("items") or []))
    if len(slides) != len(fixture_items):
        issues.append(f"slide count mismatch (expected {len(fixture_items)}, got {len(slides)})")

    total_rows = 0
    for slide_index, slide in enumerate(slides, start=1):
        if slide.get("slide_type") != "fixture_rich":
            issues.append(f"slide {slide_index} has unexpected type {slide.get('slide_type')}")
            continue
        sections = list(slide.get("sections") or [])
        if not sections:
            issues.append(f"slide {slide_index} has no sections")
            continue
        for section in sections:
            rows = list(section.get("rows") or [])
            if not rows:
                issues.append(f"slide {slide_index} section {section.get('key')} has no rows")
                continue
            total_rows += len(rows)
            for row in rows:
                if not row.get("subject_display"):
                    issues.append(f"slide {slide_index} row missing subject_display")
                if not row.get("record"):
                    issues.append(f"slide {slide_index} row missing record")

    expected_total = int(((manifest.get("counts") or {}).get("total_rows")) or 0)
    if total_rows != expected_total:
        issues.append(f"total row count mismatch (expected {expected_total}, got {total_rows})")
    return issues


def build_by_fixture_manifest(
    *,
    content_path: Path,
    scheduled_for: str,
    content: str,
    slot: str,
    label: str,
) -> dict[str, Any]:
    title, intro_lines, fixtures_raw, outro_lines = parse_by_fixture_text(content)

    fixture_items: list[dict[str, Any]] = []
    all_section_counts = {section_key: 0 for section_key in SECTION_ORDER}

    for fixture_index, fixture in enumerate(fixtures_raw, start=1):
        grouped_rows = {section_key: [] for section_key in SECTION_ORDER}
        grouped_subjects = {section_key: [] for section_key in SECTION_ORDER}

        raw_rows: list[dict[str, Any]] = []
        for row_index, raw_row in enumerate(fixture.rows, start=1):
            section_key, subject_name, market = _parse_row_label(raw_row.label)
            if section_key not in grouped_rows:
                continue
            raw_rows.append(
                {
                    "fixture_index": fixture_index,
                    "row_index": row_index,
                    "section_key": section_key,
                    "subject_name": subject_name,
                    "market": market,
                    "wins": raw_row.wins,
                    "total": raw_row.total,
                    "record": f"{raw_row.wins}/{raw_row.total}",
                    "hit_rate": (raw_row.wins / raw_row.total) if raw_row.total else 0.0,
                }
            )
            grouped_subjects[section_key].append(_normalize_name(subject_name))

        duplicate_subjects_by_section = {
            section_key: {
                candidate
                for candidate in grouped_subjects[section_key]
                if grouped_subjects[section_key].count(candidate) > 1
            }
            for section_key in SECTION_ORDER
        }

        for raw_row in raw_rows:
            section_key = str(raw_row["section_key"])
            subject_display, market_display = _subject_market_display(
                section_key=section_key,
                subject=str(raw_row["subject_name"]),
                market=str(raw_row["market"]),
                duplicate_subjects=duplicate_subjects_by_section[section_key],
            )
            row_payload = {
                "id": f"{fixture_index}:{section_key}:{raw_row['row_index']}",
                "fixture_index": fixture_index,
                "section_key": section_key,
                "subject_type": "team" if section_key == "corners" else "player",
                "subject_name": raw_row["subject_name"],
                "subject_display": subject_display,
                "market_display": market_display,
                "record": raw_row["record"],
                "wins": raw_row["wins"],
                "total": raw_row["total"],
                "hit_rate": raw_row["hit_rate"],
                "bar_pct": int(round(float(raw_row["hit_rate"]) * 100)),
                "assets": {},
            }
            grouped_rows[section_key].append(row_payload)
            all_section_counts[section_key] += 1

        sections = []
        total_rows = 0
        for section_key in SECTION_ORDER:
            rows = list(grouped_rows[section_key])
            if not rows:
                continue
            total_rows += len(rows)
            sections.append(
                {
                    "key": section_key,
                    "title": SECTION_META[section_key]["title"],
                    "color": SECTION_META[section_key]["color"],
                    "rows": rows,
                }
            )

        fixture_items.append(
            {
                "slide_type": "fixture_rich",
                "fixture_index": fixture_index,
                "header": fixture.header,
                "fixture_id": None,
                "home_display": fixture.home_display,
                "away_display": fixture.away_display,
                "kickoff_label": _format_kickoff_label(fixture.kickoff),
                "date_badge": _format_date_badge(scheduled_for),
                "home_team": {
                    "team_id": None,
                    "name": fixture.home_display,
                    "display_name": fixture.home_display,
                    "badge_url": None,
                    "accent_color": _team_accent(fixture.home_display),
                },
                "away_team": {
                    "team_id": None,
                    "name": fixture.away_display,
                    "display_name": fixture.away_display,
                    "badge_url": None,
                    "accent_color": _team_accent(fixture.away_display),
                },
                "sections": sections,
                "row_count": total_rows,
                "density": _density_for_total_rows(total_rows),
            }
        )

    _try_enrich_with_db(fixture_items, scheduled_for=scheduled_for)

    slides: list[dict[str, Any]] = []
    for fixture in fixture_items:
        slide = dict(fixture)
        slides.append(slide)

    for idx, slide in enumerate(slides, start=1):
        slide["slide_number"] = idx
        slide["slide_count"] = len(slides)
        slide["fixture_count"] = len(slides)

    manifest = {
        "version": 2,
        "generated_at": _utc_now_iso(),
        "channel": "instagram",
        "format": "carousel",
        "variant": "by_fixture_rich_prototype",
        "source": "by_fixture_text",
        "slot": slot,
        "scheduled_for": scheduled_for,
        "label": label,
        "title": title,
        "subtitle": "All data driven based on recent form",
        "intro_lines": intro_lines,
        "outro_lines": outro_lines,
        "content_path": str(content_path),
        "counts": {
            "fixture_count": len(fixture_items),
            "total_rows": sum(int(item.get("row_count") or 0) for item in fixture_items),
            "max_rows_per_fixture": max((int(item.get("row_count") or 0) for item in fixture_items), default=0),
            "by_section": {
                SECTION_META[key]["title"]: int(count)
                for key, count in all_section_counts.items()
                if count > 0
            },
        },
        "fixtures": {"items": fixture_items},
        "caption": "\n\n".join(
            [part for part in [title, *intro_lines, *outro_lines] if part]
        ).strip(),
        "slides": slides,
    }

    issues = verify_by_fixture_manifest(manifest)
    manifest["verification"] = {"ok": not issues, "issues": issues}
    fingerprint_payload = {
        "variant": manifest["variant"],
        "scheduled_for": scheduled_for,
        "title": title,
        "slides": slides,
    }
    manifest["content_fingerprint"] = _canonical_hash(fingerprint_payload)
    return manifest
