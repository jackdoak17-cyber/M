"""Generate shot props posts for upcoming fixtures."""

from __future__ import annotations

import argparse
import json
import logging
from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.instagram.shot_props_manifest import (
    ThresholdConfig,
    build_shot_props_carousel_manifest,
)
from src.prop_bot.engine.baseline import calculate_player_baseline
from src.prop_bot.engine.odds import get_player_market_odds, get_team_win_odds
from src.prop_bot.engine.players import get_eligible_players
from src.prop_bot.config import LEAGUES
from src.prop_bot.db import db_cursor
from src.prop_bot.models import Fixture

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

OUTPUT_DIR = Path("output/shot_props")
INSTAGRAM_MANIFEST_DIR = OUTPUT_DIR / "instagram"

STAT_CONFIGS = [
    {"label": "1+ Shot", "stat_type_id": 42, "market_key": "player_shots", "threshold": 1},
    {"label": "2+ Shots", "stat_type_id": 42, "market_key": "player_shots", "threshold": 2},
    {"label": "1+ SOT", "stat_type_id": 86, "market_key": "player_shots_on_target", "threshold": 1},
]
SECTION_ORDER = ["1+ Shot", "2+ Shots", "1+ SOT"]

BET365_IDS = (2,)
MIN_STARTS = 7
MAX_STARTS = 20
MAX_CANDIDATE_LINE_CHARS = 46

VALUE_MIN_HIT_PCT = 0.75
VALUE_MIN_ODDS = 1.72
HIGH_PROB_MIN_HIT_PCT = 0.90
HIGH_PROB_MIN_ODDS = 1.30
MAX_TEAM_ML_ODDS = 5.0

VALUE_TITLE = ""
WEEKEND_VALUE_TITLE = ""
VALUE_INTRO = (
    "\U0001f4ca Weekend Shot Props list\n"
    "Min 7 games \u00b7 75%+ hit rate \u00b7 Odds >1.72 \u00b7 All Bet365\n"
    "Any value here?"
)
HIGH_PROB_TITLE = "\U0001f4ca Today's High Probability Stats & Odds List \U0001f512"
HIGH_PROB_INTRO = (
    "Players hitting 1+, 2+ shots and 1+ SOT in 90%+ of recent games "
    "(min n=7) with odds >1.30 \u2014 any value here?"
)

SHORT_TEAM_NAMES: dict[str, str] = {
    "AFC Bournemouth": "Bournemouth",
    "Brighton & Hove Albion": "Brighton",
    "Crystal Palace": "Palace",
    "Leeds United": "Leeds",
    "Manchester City": "Man City",
    "Manchester United": "Man Utd",
    "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nottm Forest",
    "Tottenham Hotspur": "Spurs",
    "West Ham United": "West Ham",
    "Wolverhampton Wanderers": "Wolves",
    "Paris Saint Germain": "PSG",
    "Paris Saint-Germain": "PSG",
    "Olympique Lyonnais": "Lyon",
    "Olympique Marseille": "Marseille",
    "Olympique de Marseille": "Marseille",
    "Bayer 04 Leverkusen": "Leverkusen",
    "FC Bayern München": "Bayern",
    "FC Bayern Munich": "Bayern",
    "Borussia Dortmund": "Dortmund",
    "FSV Mainz 05": "Mainz",
    "TSG Hoffenheim": "Hoffenheim",
    "Borussia Mönchengladbach": "Gladbach",
    "Borussia Monchengladbach": "Gladbach",
    "Sheffield United": "Sheff Utd",
    "Sheffield Wednesday": "Sheff Wed",
}


@dataclass
class QualifyingPlayer:
    player_id: int
    player_name: str
    team_id: int
    team_name: str
    fixture_id: int
    fixture_label: str
    league_id: int
    league_name: str
    stat_label: str
    stat_type_id: int
    market_key: str
    threshold: int
    hits: int
    sample: int
    odds: float
    bookmaker_id: int | None = None
    started_values: list[Any] | None = None


@dataclass
class CandidateAuditRow:
    fixture_id: int
    fixture_label: str
    league_id: int
    league_name: str
    player_id: int
    player_name: str
    team_id: int
    team_name: str
    stat_label: str
    stat_type_id: int
    market_key: str
    threshold: int
    raw_values: list[Any]
    raw_minutes: list[Any]
    starter_only_values: list[Any]
    starter_only_minutes: list[Any]
    status: str
    reasons: list[str]
    hits: int | None = None
    sample: int | None = None
    odds: float | None = None
    bookmaker_id: int | None = None
    qualifies_value: bool = False
    qualifies_high_prob: bool = False


def _fixture_label(fixture: Any) -> str:
    return f"{fixture.home_team} vs {fixture.away_team}"


def _get_fixtures_for_dates(target_dates: list[date]) -> list[Fixture]:
    """Fetch upcoming fixtures for exact UTC dates across configured leagues."""
    dates = sorted(set(target_dates))
    if not dates:
        return []
    league_ids = tuple(LEAGUES.keys())
    if not league_ids:
        return []

    query = """
        select f.id as fixture_id,
               f.starting_at,
               f.home_team_id,
               f.away_team_id,
               ht.name as home_team,
               at.name as away_team,
               f.league_id
        from fixtures f
        join teams ht on f.home_team_id = ht.id
        join teams at on f.away_team_id = at.id
        where f.league_id = any(%s)
          and (f.starting_at at time zone 'utc')::date = any(%s)
          and f.starting_at >= now()
          and f.home_score is null
          and f.away_score is null
        order by f.starting_at;
    """

    fixtures: list[Fixture] = []
    with db_cursor() as cur:
        cur.execute(query, (list(league_ids), dates))
        for row in cur.fetchall():
            league_id = int(row["league_id"])
            fixtures.append(
                Fixture(
                    fixture_id=int(row["fixture_id"]),
                    starting_at=row["starting_at"],
                    home_team_id=int(row["home_team_id"]),
                    away_team_id=int(row["away_team_id"]),
                    home_team=row["home_team"],
                    away_team=row["away_team"],
                    league_id=league_id,
                    league_name=LEAGUES.get(league_id, f"League {league_id}"),
                ),
            )
    return fixtures


def _value_scope_dates_for_target(target_date: date) -> list[date]:
    """Weekend behavior: Saturday value post combines Sat+Sun, Sunday value post is skipped."""
    weekday = target_date.weekday()
    if weekday == 5:  # Saturday target -> Friday value post covers weekend
        return [target_date, target_date + timedelta(days=1)]
    if weekday == 6:  # Sunday target -> already covered by Saturday-combined value post
        return []
    return [target_date]


def _serialize_number(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else round(value, 4)
    try:
        float_value = float(value)
    except (TypeError, ValueError):
        return value
    return int(float_value) if float_value.is_integer() else round(float_value, 4)


def _serialize_list(values: list[Any]) -> list[Any]:
    return [_serialize_number(value) for value in values]


def _recent_started_samples(
    raw_values: list[Any],
    raw_minutes: list[Any],
    min_started_minutes: int = 60,
    max_starts: int = MAX_STARTS,
) -> list[tuple[Any, Any]]:
    """Return only starter rows (minutes >= threshold), preserving recency order."""
    starts = [(val, mins) for val, mins in zip(raw_values, raw_minutes) if mins >= min_started_minutes]
    return starts[:max_starts]


def _passes_team_ml_filter(team_ml_odds: float | None) -> bool:
    # Require an explicit team ML price so underdog suppression is always enforced.
    return team_ml_odds is not None and team_ml_odds <= MAX_TEAM_ML_ODDS


def _short_team_name(team_name: str) -> str:
    name = str(team_name or "").strip()
    if not name:
        return name
    if name in SHORT_TEAM_NAMES:
        return SHORT_TEAM_NAMES[name]
    if name.startswith("Sheffield "):
        return name

    shortened = name
    for suffix in (" United", " FC", " CF", " AFC", " SC"):
        if shortened.endswith(suffix) and len(shortened) > len(suffix):
            shortened = shortened[: -len(suffix)].strip()
            break
    return shortened or name


def _short_player_name(player_name: str) -> str:
    tokens = [token for token in str(player_name or "").strip().split() if token]
    if not tokens:
        return str(player_name or "")
    if len(tokens) == 1:
        return tokens[0]
    first = tokens[0]
    surname = tokens[-1]
    initial = first[0].upper() if first else ""
    return f"{initial}.{surname}" if initial else surname


def _trim_for_line(value: str, max_len: int) -> str:
    text = str(value or "")
    if len(text) <= max_len:
        return text
    if max_len <= 3:
        return text[:max_len]
    return text[: max_len - 3].rstrip() + "..."


def _best_qualifying_window(
    candidate: QualifyingPlayer,
    min_hit_pct: float,
    *,
    min_sample: int = MIN_STARTS,
    max_sample: int = MAX_STARTS,
) -> tuple[int, int] | None:
    started_values = list(candidate.started_values or [])
    if started_values:
        cap = min(len(started_values), max_sample)
        best: tuple[int, int] | None = None
        for n in range(min_sample, cap + 1):
            sample_values = started_values[:n]
            hits = sum(1 for value in sample_values if float(value) >= candidate.threshold)
            if hits / n >= min_hit_pct:
                best = (hits, n)
        return best

    # Backward-compatible fallback for synthetic test candidates without started_values.
    if candidate.sample >= min_sample and candidate.sample > 0 and (candidate.hits / candidate.sample) >= min_hit_pct:
        return (candidate.hits, candidate.sample)
    return None


def _qualifies_for_thresholds(candidate: QualifyingPlayer, min_hit_pct: float, min_odds: float) -> bool:
    if candidate.odds <= min_odds:
        return False
    return _best_qualifying_window(candidate, min_hit_pct) is not None


def _qualifies_value(candidate: QualifyingPlayer) -> bool:
    return _qualifies_for_thresholds(candidate, VALUE_MIN_HIT_PCT, VALUE_MIN_ODDS)


def _qualifies_high_prob(candidate: QualifyingPlayer) -> bool:
    return _qualifies_for_thresholds(candidate, HIGH_PROB_MIN_HIT_PCT, HIGH_PROB_MIN_ODDS)


def _render_candidate_line(player: QualifyingPlayer) -> str:
    short_name = _short_player_name(player.player_name)
    team_name = _short_team_name(player.team_name)
    tail = f" {player.hits}/{player.sample} @{player.odds:.2f}"
    line = f"\u2192 {short_name} ({team_name}){tail}"
    if len(line) <= MAX_CANDIDATE_LINE_CHARS:
        return line

    team_name = _trim_for_line(team_name, 12)
    line = f"\u2192 {short_name} ({team_name}){tail}"
    if len(line) <= MAX_CANDIDATE_LINE_CHARS:
        return line

    remaining = MAX_CANDIDATE_LINE_CHARS - len("\u2192  ()") - len(team_name) - len(tail)
    short_name = _trim_for_line(short_name, max(6, remaining))
    return f"\u2192 {short_name} ({team_name}){tail}"


def _select_candidates_for_post(
    candidates: list[QualifyingPlayer],
    min_hit_pct: float,
    min_odds: float,
) -> dict[str, list[QualifyingPlayer]]:
    sections: dict[str, list[QualifyingPlayer]] = {label: [] for label in SECTION_ORDER}
    for candidate in candidates:
        if candidate.odds <= min_odds:
            continue
        best_window = _best_qualifying_window(candidate, min_hit_pct)
        if best_window is None:
            continue
        hits, sample = best_window
        selected = replace(candidate, hits=hits, sample=sample)
        if selected.stat_label in sections:
            sections[selected.stat_label].append(selected)
    for players in sections.values():
        players.sort(key=lambda p: (p.hits / p.sample, p.odds), reverse=True)
    return sections


def _filter_and_format(
    candidates: list[QualifyingPlayer],
    min_hit_pct: float,
    min_odds: float,
    title: str,
    intro: str,
) -> str:
    """Filter candidates by thresholds and format post text."""
    sections = _select_candidates_for_post(candidates, min_hit_pct, min_odds)
    if not any(sections.values()):
        return ""

    lines: list[str] = []
    if title.strip():
        lines.extend([title, ""])
    lines.extend([intro, ""])

    for label in SECTION_ORDER:
        players = sections[label]
        if not players:
            continue
        lines.append(f"\U0001f3af {label}")
        for player in players:
            lines.append(_render_candidate_line(player))
        lines.append("")

    lines.append("All odds correct at time of collation. Not tips just bets meeting a stat criteria")

    return "\n".join(lines).strip()


def _extract_section_lines(post_text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for raw_line in post_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("\U0001f3af "):
            current_section = line.split(" ", 1)[1].strip()
            sections.setdefault(current_section, [])
            continue
        if line.startswith("\u2192 "):
            if current_section is None:
                continue
            sections.setdefault(current_section, []).append(line)
    return sections


def _verify_post_matches_candidates(
    post_text: str,
    candidates: list[QualifyingPlayer],
    min_hit_pct: float,
    min_odds: float,
    post_label: str,
) -> list[str]:
    expected_sections = _select_candidates_for_post(candidates, min_hit_pct, min_odds)
    expected_lines = {
        section: [_render_candidate_line(player) for player in players]
        for section, players in expected_sections.items()
        if players
    }
    actual_lines = {
        section: lines
        for section, lines in _extract_section_lines(post_text).items()
        if lines
    }

    issues: list[str] = []
    if not expected_lines and post_text.strip():
        issues.append(f"{post_label}: post has content but zero qualifiers are expected.")
        return issues
    if expected_lines and not post_text.strip():
        issues.append(f"{post_label}: expected qualifiers but post is empty.")
        return issues

    all_sections = sorted(set(expected_lines) | set(actual_lines))
    for section in all_sections:
        expected = expected_lines.get(section, [])
        actual = actual_lines.get(section, [])
        if expected != actual:
            issues.append(
                f"{post_label}: section '{section}' mismatch (expected {len(expected)} lines, got {len(actual)})."
            )
            missing = [line for line in expected if line not in actual]
            unexpected = [line for line in actual if line not in expected]
            if missing:
                issues.append(f"{post_label}: missing in '{section}': {' | '.join(missing[:5])}")
            if unexpected:
                issues.append(f"{post_label}: unexpected in '{section}': {' | '.join(unexpected[:5])}")
    return issues


def _write_or_remove_output(path: Path, content: str, empty_log_message: str) -> None:
    if content:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        log.info("Wrote %s", path)
        return
    if path.exists():
        path.unlink()
        log.info("Removed stale file %s", path)
    log.info(empty_log_message)


def _write_or_remove_json(path: Path, payload: dict[str, Any] | None, empty_log_message: str) -> None:
    if payload:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        log.info("Wrote %s", path)
        return
    if path.exists():
        path.unlink()
        log.info("Removed stale file %s", path)
    log.info(empty_log_message)


def _get_candidates(fixtures, audit_rows: list[CandidateAuditRow] | None = None) -> list[QualifyingPlayer]:
    """Get all candidates with Bet365 odds across all fixtures."""
    candidates: list[QualifyingPlayer] = []
    team_ml_cache: dict[tuple[int, int], float | None] = {}

    for fixture in fixtures:
        players = get_eligible_players(fixture)
        fixture_label = _fixture_label(fixture)

        for player in players:
            cache_key = (fixture.fixture_id, player.team_id)
            if cache_key not in team_ml_cache:
                is_home = int(player.team_id) == int(fixture.home_team_id)
                team_ml_cache[cache_key] = get_team_win_odds(
                    fixture.fixture_id,
                    player.team_id,
                    is_home=is_home,
                    bookmaker_ids=BET365_IDS,
                )
            team_ml_odds = team_ml_cache[cache_key]
            if not _passes_team_ml_filter(team_ml_odds):
                if audit_rows is not None:
                    for cfg in STAT_CONFIGS:
                        audit_rows.append(
                            CandidateAuditRow(
                                fixture_id=fixture.fixture_id,
                                fixture_label=fixture_label,
                                league_id=fixture.league_id,
                                league_name=fixture.league_name,
                                player_id=player.player_id,
                                player_name=player.player_name,
                                team_id=player.team_id,
                                team_name=player.team_name,
                                stat_label=cfg["label"],
                                stat_type_id=int(cfg["stat_type_id"]),
                                market_key=str(cfg["market_key"]),
                                threshold=int(cfg["threshold"]),
                                raw_values=[],
                                raw_minutes=[],
                                starter_only_values=[],
                                starter_only_minutes=[],
                                status="excluded",
                                reasons=["team_ml_over_5"],
                            )
                        )
                continue

            # Cache baselines by stat_type_id to avoid duplicate DB calls
            baselines: dict[int, dict | None] = {}

            for cfg in STAT_CONFIGS:
                stat_type_id = cfg["stat_type_id"]

                if stat_type_id not in baselines:
                    baselines[stat_type_id] = calculate_player_baseline(
                        player.player_id, stat_type_id, fixture.league_id
                    )

                baseline = baselines[stat_type_id]
                if not baseline:
                    if audit_rows is not None:
                        audit_rows.append(
                            CandidateAuditRow(
                                fixture_id=fixture.fixture_id,
                                fixture_label=fixture_label,
                                league_id=fixture.league_id,
                                league_name=fixture.league_name,
                                player_id=player.player_id,
                                player_name=player.player_name,
                                team_id=player.team_id,
                                team_name=player.team_name,
                                stat_label=cfg["label"],
                                stat_type_id=stat_type_id,
                                market_key=cfg["market_key"],
                                threshold=int(cfg["threshold"]),
                                raw_values=[],
                                raw_minutes=[],
                                starter_only_values=[],
                                starter_only_minutes=[],
                                status="missing_baseline",
                                reasons=["missing_baseline"],
                            )
                        )
                    continue

                raw_values = list(baseline.get("raw_values") or [])
                raw_minutes = list(baseline.get("raw_minutes") or [])
                starts = _recent_started_samples(raw_values, raw_minutes)
                starter_only_values = [val for val, _ in starts]
                starter_only_minutes = [mins for _, mins in starts]

                if not raw_values or not raw_minutes:
                    if audit_rows is not None:
                        audit_rows.append(
                            CandidateAuditRow(
                                fixture_id=fixture.fixture_id,
                                fixture_label=fixture_label,
                                league_id=fixture.league_id,
                                league_name=fixture.league_name,
                                player_id=player.player_id,
                                player_name=player.player_name,
                                team_id=player.team_id,
                                team_name=player.team_name,
                                stat_label=cfg["label"],
                                stat_type_id=stat_type_id,
                                market_key=cfg["market_key"],
                                threshold=int(cfg["threshold"]),
                                raw_values=_serialize_list(raw_values),
                                raw_minutes=_serialize_list(raw_minutes),
                                starter_only_values=_serialize_list(starter_only_values),
                                starter_only_minutes=_serialize_list(starter_only_minutes),
                                status="empty_baseline",
                                reasons=["empty_baseline"],
                            )
                        )
                    continue

                # Last match check: most recent game must be a start.
                # Bench appearances are excluded from hit-rate numerator/denominator.
                if raw_minutes[0] < 60:
                    if audit_rows is not None:
                        audit_rows.append(
                            CandidateAuditRow(
                                fixture_id=fixture.fixture_id,
                                fixture_label=fixture_label,
                                league_id=fixture.league_id,
                                league_name=fixture.league_name,
                                player_id=player.player_id,
                                player_name=player.player_name,
                                team_id=player.team_id,
                                team_name=player.team_name,
                                stat_label=cfg["label"],
                                stat_type_id=stat_type_id,
                                market_key=cfg["market_key"],
                                threshold=int(cfg["threshold"]),
                                raw_values=_serialize_list(raw_values),
                                raw_minutes=_serialize_list(raw_minutes),
                                starter_only_values=_serialize_list(starter_only_values),
                                starter_only_minutes=_serialize_list(starter_only_minutes),
                                status="excluded",
                                reasons=["last_match_not_started"],
                            )
                        )
                    continue

                if len(starts) < MIN_STARTS:
                    if audit_rows is not None:
                        audit_rows.append(
                            CandidateAuditRow(
                                fixture_id=fixture.fixture_id,
                                fixture_label=fixture_label,
                                league_id=fixture.league_id,
                                league_name=fixture.league_name,
                                player_id=player.player_id,
                                player_name=player.player_name,
                                team_id=player.team_id,
                                team_name=player.team_name,
                                stat_label=cfg["label"],
                                stat_type_id=stat_type_id,
                                market_key=cfg["market_key"],
                                threshold=int(cfg["threshold"]),
                                raw_values=_serialize_list(raw_values),
                                raw_minutes=_serialize_list(raw_minutes),
                                starter_only_values=_serialize_list(starter_only_values),
                                starter_only_minutes=_serialize_list(starter_only_minutes),
                                status="excluded",
                                reasons=["insufficient_started_sample"],
                                sample=len(starts),
                            )
                        )
                    continue

                threshold = int(cfg["threshold"])
                hits = sum(1 for val, _ in starts if val >= threshold)
                sample = len(starts)

                odds_data = get_player_market_odds(
                    fixture.fixture_id,
                    player.player_id,
                    cfg["market_key"],
                    threshold,
                    bookmaker_ids=BET365_IDS,
                )
                if not odds_data:
                    if audit_rows is not None:
                        audit_rows.append(
                            CandidateAuditRow(
                                fixture_id=fixture.fixture_id,
                                fixture_label=fixture_label,
                                league_id=fixture.league_id,
                                league_name=fixture.league_name,
                                player_id=player.player_id,
                                player_name=player.player_name,
                                team_id=player.team_id,
                                team_name=player.team_name,
                                stat_label=cfg["label"],
                                stat_type_id=stat_type_id,
                                market_key=cfg["market_key"],
                                threshold=threshold,
                                raw_values=_serialize_list(raw_values),
                                raw_minutes=_serialize_list(raw_minutes),
                                starter_only_values=_serialize_list(starter_only_values),
                                starter_only_minutes=_serialize_list(starter_only_minutes),
                                status="excluded",
                                reasons=["missing_bet365_odds"],
                                hits=hits,
                                sample=sample,
                            )
                        )
                    continue

                candidate = QualifyingPlayer(
                    player_id=player.player_id,
                    player_name=player.player_name,
                    team_id=player.team_id,
                    team_name=player.team_name,
                    fixture_id=fixture.fixture_id,
                    fixture_label=fixture_label,
                    league_id=fixture.league_id,
                    league_name=fixture.league_name,
                    stat_label=cfg["label"],
                    stat_type_id=stat_type_id,
                    market_key=cfg["market_key"],
                    threshold=threshold,
                    hits=hits,
                    sample=sample,
                    odds=float(odds_data["price"]),
                    bookmaker_id=int(odds_data["bookmaker_id"]) if odds_data.get("bookmaker_id") is not None else None,
                    started_values=_serialize_list(starter_only_values),
                )
                candidates.append(candidate)

                if audit_rows is not None:
                    audit_rows.append(
                        CandidateAuditRow(
                            fixture_id=fixture.fixture_id,
                            fixture_label=fixture_label,
                            league_id=fixture.league_id,
                            league_name=fixture.league_name,
                            player_id=player.player_id,
                            player_name=player.player_name,
                            team_id=player.team_id,
                            team_name=player.team_name,
                            stat_label=cfg["label"],
                            stat_type_id=stat_type_id,
                            market_key=cfg["market_key"],
                            threshold=threshold,
                            raw_values=_serialize_list(raw_values),
                            raw_minutes=_serialize_list(raw_minutes),
                            starter_only_values=_serialize_list(starter_only_values),
                            starter_only_minutes=_serialize_list(starter_only_minutes),
                            status="candidate",
                            reasons=[],
                            hits=hits,
                            sample=sample,
                            odds=float(odds_data["price"]),
                            bookmaker_id=int(odds_data["bookmaker_id"]) if odds_data.get("bookmaker_id") is not None else None,
                            qualifies_value=_qualifies_value(candidate),
                            qualifies_high_prob=_qualifies_high_prob(candidate),
                        )
                    )

    return candidates


def _build_audit_payload(
    target_date: date,
    fixtures: list[Any],
    candidates: list[QualifyingPlayer],
    audit_rows: list[CandidateAuditRow],
    *,
    value_candidates: list[QualifyingPlayer] | None = None,
) -> dict[str, Any]:
    value_base = value_candidates if value_candidates is not None else candidates
    value_sections = _select_candidates_for_post(value_base, VALUE_MIN_HIT_PCT, VALUE_MIN_ODDS)
    high_prob_sections = _select_candidates_for_post(candidates, HIGH_PROB_MIN_HIT_PCT, HIGH_PROB_MIN_ODDS)
    status_counts = Counter(row.status for row in audit_rows)
    reason_counts = Counter(reason for row in audit_rows for reason in row.reasons)

    fixtures_by_league = Counter(getattr(fixture, "league_name", f"League {fixture.league_id}") for fixture in fixtures)

    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "target_date": target_date.isoformat(),
        "config": {
            "min_starts": MIN_STARTS,
            "max_starts": MAX_STARTS,
            "bet365_bookmaker_ids": list(BET365_IDS),
            "value": {"min_hit_pct": VALUE_MIN_HIT_PCT, "min_odds": VALUE_MIN_ODDS},
            "high_probability": {"min_hit_pct": HIGH_PROB_MIN_HIT_PCT, "min_odds": HIGH_PROB_MIN_ODDS},
            "section_order": SECTION_ORDER,
        },
        "fixtures": {
            "count": len(fixtures),
            "by_league": dict(sorted(fixtures_by_league.items())),
            "items": [
                {
                    "fixture_id": fixture.fixture_id,
                    "league_id": fixture.league_id,
                    "league_name": fixture.league_name,
                    "starting_at": fixture.starting_at.isoformat() if hasattr(fixture.starting_at, "isoformat") else str(fixture.starting_at),
                    "home_team": fixture.home_team,
                    "away_team": fixture.away_team,
                }
                for fixture in fixtures
            ],
        },
        "counts": {
            "audit_rows": len(audit_rows),
            "candidates_with_odds": len(candidates),
            "value_qualifiers": sum(len(rows) for rows in value_sections.values()),
            "high_probability_qualifiers": sum(len(rows) for rows in high_prob_sections.values()),
            "status": dict(sorted(status_counts.items())),
            "exclude_reasons": dict(sorted(reason_counts.items())),
        },
        "qualifiers": {
            "value": {
                "by_section": {
                    section: [asdict(player) for player in rows]
                    for section, rows in value_sections.items()
                    if rows
                }
            },
            "high_probability": {
                "by_section": {
                    section: [asdict(player) for player in rows]
                    for section, rows in high_prob_sections.items()
                    if rows
                }
            },
        },
        "audit_rows": [asdict(row) for row in audit_rows],
    }


def generate_shot_props(
    target_date: date,
    *,
    write_audit: bool = False,
    verify_outputs: bool = False,
) -> dict[str, Any]:
    """Generate both post files for the given target date."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    date_str = target_date.isoformat()
    value_date = target_date - timedelta(days=1)
    value_path = OUTPUT_DIR / f"{value_date.isoformat()}_potential_value.txt"
    hp_path = OUTPUT_DIR / f"{date_str}_high_probability.txt"
    audit_path = OUTPUT_DIR / f"{date_str}_audit.json"
    value_ig_manifest_path = INSTAGRAM_MANIFEST_DIR / f"{value_date.isoformat()}_potential_value.json"
    hp_ig_manifest_path = INSTAGRAM_MANIFEST_DIR / f"{date_str}_high_probability.json"

    log.info("Generating shot props for %s", date_str)

    fixtures = _get_fixtures_for_dates([target_date])

    if not fixtures:
        _write_or_remove_output(value_path, "", f"No fixtures found for {date_str}; no potential value post.")
        _write_or_remove_output(hp_path, "", f"No fixtures found for {date_str}; no high probability post.")
        summary = {
            "target_date": date_str,
            "fixture_count": 0,
            "candidate_count": 0,
            "value_qualifier_count": 0,
            "high_probability_qualifier_count": 0,
            "value_path": str(value_path),
            "high_probability_path": str(hp_path),
            "audit_path": str(audit_path) if write_audit else None,
            "instagram_value_manifest_path": str(value_ig_manifest_path),
            "instagram_high_probability_manifest_path": str(hp_ig_manifest_path),
            "verification_issues": [],
        }
        _write_or_remove_json(
            value_ig_manifest_path,
            None,
            f"No fixtures found for {date_str}; no Instagram potential value manifest.",
        )
        _write_or_remove_json(
            hp_ig_manifest_path,
            None,
            f"No fixtures found for {date_str}; no Instagram high probability manifest.",
        )
        if write_audit:
            audit_payload = {
                "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                "target_date": date_str,
                "fixtures": {"count": 0, "by_league": {}, "items": []},
                "counts": {
                    "audit_rows": 0,
                    "candidates_with_odds": 0,
                    "value_qualifiers": 0,
                    "high_probability_qualifiers": 0,
                    "status": {},
                    "exclude_reasons": {},
                },
                "qualifiers": {"value": {"by_section": {}}, "high_probability": {"by_section": {}}},
                "audit_rows": [],
            }
            audit_path.write_text(json.dumps(audit_payload, indent=2), encoding="utf-8")
            log.info("Wrote %s", audit_path)
        return summary

    log.info("Found %d fixtures for %s", len(fixtures), date_str)

    audit_rows: list[CandidateAuditRow] | None = [] if write_audit else None
    candidates = _get_candidates(fixtures, audit_rows=audit_rows)
    log.info("Found %d total candidates", len(candidates))

    value_scope_dates = _value_scope_dates_for_target(target_date)
    combined_weekend_value = len(value_scope_dates) > 1
    if combined_weekend_value:
        extra_value_dates = [d for d in value_scope_dates if d != target_date]
        value_fixtures = list(fixtures)
        extra_value_fixtures = _get_fixtures_for_dates(extra_value_dates)
        value_fixtures.extend(extra_value_fixtures)
        log.info(
            "Combining potential value post across weekend dates %s (%d fixtures).",
            ", ".join(d.isoformat() for d in value_scope_dates),
            len(value_fixtures),
        )
        extra_value_candidates = _get_candidates(extra_value_fixtures)
        value_candidates = [*candidates, *extra_value_candidates]
        log.info(
            "Found %d total weekend value candidates (%d Saturday + %d Sunday)",
            len(value_candidates),
            len(candidates),
            len(extra_value_candidates),
        )
    elif not value_scope_dates:
        value_candidates = []
        log.info("Skipping potential value post for %s (covered by weekend combined post).", date_str)
    else:
        value_candidates = candidates

    value_title = WEEKEND_VALUE_TITLE if combined_weekend_value else VALUE_TITLE

    value_sections = _select_candidates_for_post(value_candidates, VALUE_MIN_HIT_PCT, VALUE_MIN_ODDS)
    value_text = _filter_and_format(
        value_candidates,
        min_hit_pct=VALUE_MIN_HIT_PCT,
        min_odds=VALUE_MIN_ODDS,
        title=value_title,
        intro=VALUE_INTRO,
    )

    _write_or_remove_output(value_path, value_text, "No qualifying players for potential value post")

    high_prob_sections = _select_candidates_for_post(candidates, HIGH_PROB_MIN_HIT_PCT, HIGH_PROB_MIN_ODDS)
    hp_text = _filter_and_format(
        candidates,
        min_hit_pct=HIGH_PROB_MIN_HIT_PCT,
        min_odds=HIGH_PROB_MIN_ODDS,
        title=HIGH_PROB_TITLE,
        intro=HIGH_PROB_INTRO,
    )

    _write_or_remove_output(hp_path, hp_text, "No qualifying players for high probability post")

    value_manifest = build_shot_props_carousel_manifest(
        post_type="potential_value",
        scheduled_for=value_date,
        source_target_date=target_date,
        fixture_dates=value_scope_dates or [target_date],
        title=value_title,
        intro=VALUE_INTRO,
        threshold_cfg=ThresholdConfig(
            min_hit_pct=VALUE_MIN_HIT_PCT,
            min_odds=VALUE_MIN_ODDS,
            min_starts=MIN_STARTS,
        ),
        section_order=SECTION_ORDER,
        sections=value_sections,
    )
    _write_or_remove_json(
        value_ig_manifest_path,
        value_manifest,
        "No qualifying players for Instagram potential value manifest",
    )

    hp_manifest = build_shot_props_carousel_manifest(
        post_type="high_probability",
        scheduled_for=target_date,
        source_target_date=target_date,
        fixture_dates=[target_date],
        title=HIGH_PROB_TITLE,
        intro=HIGH_PROB_INTRO,
        threshold_cfg=ThresholdConfig(
            min_hit_pct=HIGH_PROB_MIN_HIT_PCT,
            min_odds=HIGH_PROB_MIN_ODDS,
            min_starts=MIN_STARTS,
        ),
        section_order=SECTION_ORDER,
        sections=high_prob_sections,
    )
    _write_or_remove_json(
        hp_ig_manifest_path,
        hp_manifest,
        "No qualifying players for Instagram high probability manifest",
    )

    verification_issues: list[str] = []
    if verify_outputs:
        verification_issues.extend(
            _verify_post_matches_candidates(
                value_text,
                value_candidates,
                VALUE_MIN_HIT_PCT,
                VALUE_MIN_ODDS,
                "Potential Value",
            )
        )
        verification_issues.extend(
            _verify_post_matches_candidates(
                hp_text,
                candidates,
                HIGH_PROB_MIN_HIT_PCT,
                HIGH_PROB_MIN_ODDS,
                "High Probability",
            )
        )
        if verification_issues:
            raise RuntimeError("Shot props verification failed:\n" + "\n".join(verification_issues))
        log.info("Verified post outputs match all qualifying candidates.")
        if value_manifest and not (value_manifest.get("verification") or {}).get("ok", False):
            issues = (value_manifest.get("verification") or {}).get("issues") or []
            raise RuntimeError("Instagram potential value manifest verification failed:\n" + "\n".join(issues))
        if hp_manifest and not (hp_manifest.get("verification") or {}).get("ok", False):
            issues = (hp_manifest.get("verification") or {}).get("issues") or []
            raise RuntimeError("Instagram high probability manifest verification failed:\n" + "\n".join(issues))
        if value_manifest or hp_manifest:
            log.info("Verified Instagram carousel manifests.")

    if write_audit and audit_rows is not None:
        audit_payload = _build_audit_payload(
            target_date,
            fixtures,
            candidates,
            audit_rows,
            value_candidates=value_candidates,
        )
        audit_payload["value_scope_dates"] = [d.isoformat() for d in value_scope_dates]
        audit_payload["value_scope_combined_weekend"] = combined_weekend_value
        audit_path.write_text(json.dumps(audit_payload, indent=2), encoding="utf-8")
        log.info("Wrote %s", audit_path)

    value_qualifier_count = sum(1 for candidate in value_candidates if _qualifies_value(candidate))
    high_prob_qualifier_count = sum(1 for candidate in candidates if _qualifies_high_prob(candidate))
    return {
        "target_date": date_str,
        "fixture_count": len(fixtures),
        "candidate_count": len(candidates),
        "value_qualifier_count": value_qualifier_count,
        "high_probability_qualifier_count": high_prob_qualifier_count,
        "value_path": str(value_path),
        "high_probability_path": str(hp_path),
        "audit_path": str(audit_path) if write_audit else None,
        "instagram_value_manifest_path": str(value_ig_manifest_path),
        "instagram_high_probability_manifest_path": str(hp_ig_manifest_path),
        "verification_issues": verification_issues,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate shot props posts")
    parser.add_argument(
        "--date",
        type=str,
        help="Target date (YYYY-MM-DD). Defaults to tomorrow.",
    )
    parser.add_argument(
        "--audit",
        action="store_true",
        help="Write a candidate-level audit JSON alongside the generated posts.",
    )
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Verify generated post text contains every qualifying candidate for each post type.",
    )
    args = parser.parse_args()

    if args.date:
        target = date.fromisoformat(args.date)
    else:
        target = (datetime.utcnow() + timedelta(days=1)).date()

    generate_shot_props(target, write_audit=args.audit, verify_outputs=args.verify)
