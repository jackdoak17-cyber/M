from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable


DEFAULT_MAX_ROWS_PER_SECTION_SLIDE = 8


@dataclass(frozen=True)
class ThresholdConfig:
    min_hit_pct: float
    min_odds: float
    min_starts: int


def _human_short_date(value: date) -> str:
    return value.strftime("%a %d %b %Y")


def _human_short_date_no_year(value: date) -> str:
    return value.strftime("%a %d %b")


def _fixture_window_label(fixture_dates: list[date]) -> str:
    unique_dates = sorted(set(fixture_dates))
    if not unique_dates:
        return ""
    if len(unique_dates) == 1:
        return _human_short_date(unique_dates[0])
    first = unique_dates[0]
    last = unique_dates[-1]
    if first.year == last.year:
        return f"{_human_short_date_no_year(first)} - {last.strftime('%a %d %b %Y')}"
    return f"{_human_short_date(first)} - {_human_short_date(last)}"


def _threshold_bar_text(cfg: ThresholdConfig) -> str:
    hit_pct = int(round(cfg.min_hit_pct * 100))
    return f"{hit_pct}%+ HIT RATE · ODDS >{cfg.min_odds:.2f} · MIN N={cfg.min_starts}"


def _post_badge(post_type: str) -> str:
    return "Stats & Odds List" if post_type == "potential_value" else "High Probability List"


def _title_words(post_type: str) -> tuple[str, str]:
    if post_type == "potential_value":
        return ("POTENTIAL", "VALUE")
    return ("HIGH", "PROBABILITY")


def _row_key(row: dict[str, Any]) -> str:
    return str(row["id"])


def _chunked(items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    if size <= 0:
        raise ValueError("size must be > 0")
    return [items[i : i + size] for i in range(0, len(items), size)]


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _candidate_to_row(candidate: Any) -> dict[str, Any]:
    hit_rate = (candidate.hits / candidate.sample) if candidate.sample else 0.0
    row_id = f"{candidate.fixture_id}:{candidate.player_id}:{candidate.stat_label}:{candidate.threshold}"
    return {
        "id": row_id,
        "player_id": int(candidate.player_id),
        "player_name": candidate.player_name,
        "team_id": int(candidate.team_id),
        "team_name": candidate.team_name,
        "fixture_id": int(candidate.fixture_id),
        "fixture_label": candidate.fixture_label,
        "league_id": int(candidate.league_id),
        "league_name": candidate.league_name,
        "stat_label": candidate.stat_label,
        "threshold": int(candidate.threshold),
        "hits": int(candidate.hits),
        "sample": int(candidate.sample),
        "hit_rate": round(hit_rate, 4),
        "odds": round(float(candidate.odds), 2),
        "display": {
            "rate": f"{candidate.hits}/{candidate.sample}",
            "odds": f"@{float(candidate.odds):.2f}",
            "summary": (
                f"{candidate.player_name} ({candidate.team_name}) "
                f"won in {candidate.hits}/{candidate.sample} @{float(candidate.odds):.2f}"
            ),
        },
    }


def _rows_from_sections(section_order: list[str], sections: dict[str, list[Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for section in section_order:
        players = sections.get(section) or []
        if not players:
            continue
        out[section] = [_candidate_to_row(player) for player in players]
    return out


def _build_caption(
    *,
    post_type: str,
    fixture_dates: list[date],
    threshold_cfg: ThresholdConfig,
    section_order: list[str],
    section_rows: dict[str, list[dict[str, Any]]],
    title: str,
) -> str:
    total_rows = sum(len(rows) for rows in section_rows.values())
    fixture_window = _fixture_window_label(fixture_dates)
    lines = [
        title,
        "",
        f"Fixtures: {fixture_window}" if fixture_window else "Fixtures: TBC",
        _threshold_bar_text(threshold_cfg),
        "",
        "Included sections:",
    ]
    for section in section_order:
        count = len(section_rows.get(section, []))
        if count:
            lines.append(f"• {section}: {count}")
    if total_rows == 0:
        lines.append("• No qualifiers")

    lines.extend(
        [
            "",
            "Starter-only sample (bench appearances excluded).",
            "Players can appear in multiple sections.",
            "All odds Bet365.",
        ]
    )
    if post_type == "potential_value":
        lines.append("#ShotProps #FootballStats #BettingValue")
    else:
        lines.append("#ShotProps #FootballStats #HighProbability")
    return "\n".join(lines).strip()


def build_shot_props_carousel_manifest(
    *,
    post_type: str,
    scheduled_for: date,
    source_target_date: date,
    fixture_dates: list[date],
    title: str,
    intro: str,
    threshold_cfg: ThresholdConfig,
    section_order: list[str],
    sections: dict[str, list[Any]],
    max_rows_per_section_slide: int = DEFAULT_MAX_ROWS_PER_SECTION_SLIDE,
) -> dict[str, Any] | None:
    """Build a renderer-ready Instagram carousel manifest from sorted qualifiers."""
    section_rows = _rows_from_sections(section_order, sections)
    total_rows = sum(len(rows) for rows in section_rows.values())
    if total_rows == 0:
        return None

    slides: list[dict[str, Any]] = []
    counts_by_section = {section: len(section_rows.get(section, [])) for section in section_order if section_rows.get(section)}

    slides.append(
        {
            "slide_type": "cover",
            "post_badge": _post_badge(post_type),
            "title_words": dict(zip(("primary", "accent"), _title_words(post_type))),
            "title": title,
            "intro": intro,
            "threshold_bar": _threshold_bar_text(threshold_cfg),
            "fixture_window": _fixture_window_label(fixture_dates),
            "stats": {
                "total_players": total_rows,
                "stat_types": len([s for s in section_order if section_rows.get(s)]),
                "hit_rate_threshold_pct": int(round(threshold_cfg.min_hit_pct * 100)),
            },
        }
    )

    for section in section_order:
        rows = section_rows.get(section, [])
        if not rows:
            continue
        pages = _chunked(rows, max_rows_per_section_slide)
        for page_idx, page_rows in enumerate(pages, start=1):
            slides.append(
                {
                    "slide_type": "section",
                    "section_label": section,
                    "section_page": page_idx,
                    "section_pages": len(pages),
                    "rows": page_rows,
                    "section_total_rows": len(rows),
                }
            )

    for idx, slide in enumerate(slides, start=1):
        slide["slide_number"] = idx
        slide["slide_count"] = len(slides)

    manifest: dict[str, Any] = {
        "version": 1,
        "channel": "instagram",
        "format": "carousel",
        "source": "shot_props",
        "post_type": post_type,
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "scheduled_for": scheduled_for.isoformat(),
        "source_target_date": source_target_date.isoformat(),
        "fixture_dates": [d.isoformat() for d in sorted(set(fixture_dates))],
        "title": title,
        "intro": intro,
        "odds_source": "Bet365",
        "thresholds": {
            "min_hit_pct": threshold_cfg.min_hit_pct,
            "min_odds": threshold_cfg.min_odds,
            "min_starts": threshold_cfg.min_starts,
        },
        "counts": {
            "total_rows": total_rows,
            "by_section": counts_by_section,
        },
        "sections": {
            "by_section": section_rows,
        },
        "caption": _build_caption(
            post_type=post_type,
            fixture_dates=fixture_dates,
            threshold_cfg=threshold_cfg,
            section_order=section_order,
            section_rows=section_rows,
            title=title,
        ),
        "slides": slides,
    }

    verification_issues = verify_shot_props_carousel_manifest(manifest)
    manifest["verification"] = {
        "ok": not verification_issues,
        "issues": verification_issues,
    }

    content_fingerprint_payload = {
        "post_type": manifest["post_type"],
        "scheduled_for": manifest["scheduled_for"],
        "title": manifest["title"],
        "caption": manifest["caption"],
        "slides": manifest["slides"],
    }
    manifest["content_fingerprint"] = _canonical_hash(content_fingerprint_payload)
    return manifest


def _iter_section_rows(manifest: dict[str, Any]) -> Iterable[tuple[str, list[dict[str, Any]]]]:
    for slide in manifest.get("slides", []):
        if slide.get("slide_type") != "section":
            continue
        label = str(slide.get("section_label") or "")
        rows = list(slide.get("rows") or [])
        if not label:
            continue
        yield label, rows


def verify_shot_props_carousel_manifest(manifest: dict[str, Any]) -> list[str]:
    """Verify slide pagination preserves all rows and section counts exactly."""
    issues: list[str] = []
    slides = list(manifest.get("slides") or [])
    if not slides:
        return ["manifest has no slides"]
    if (slides[0] or {}).get("slide_type") != "cover":
        issues.append("first slide must be cover")

    counts = manifest.get("counts") or {}
    expected_total = int(counts.get("total_rows") or 0)
    expected_by_section = {str(k): int(v) for k, v in (counts.get("by_section") or {}).items()}
    expected_rows_by_section = {
        str(k): [str(row.get("id")) for row in (v or [])]
        for k, v in ((manifest.get("sections") or {}).get("by_section") or {}).items()
    }

    seen_by_section: dict[str, list[str]] = {}
    for section_label, rows in _iter_section_rows(manifest):
        seen_by_section.setdefault(section_label, [])
        for row in rows:
            row_id = row.get("id")
            if not row_id:
                issues.append(f"section '{section_label}' has row without id")
                continue
            seen_by_section[section_label].append(_row_key(row))

    actual_total = sum(len(v) for v in seen_by_section.values())
    if actual_total != expected_total:
        issues.append(f"total row count mismatch (expected {expected_total}, got {actual_total})")

    all_sections = sorted(set(expected_by_section) | set(seen_by_section))
    for section in all_sections:
        expected = expected_by_section.get(section, 0)
        actual = len(seen_by_section.get(section, []))
        if expected != actual:
            issues.append(f"section '{section}' row count mismatch (expected {expected}, got {actual})")
        expected_order = expected_rows_by_section.get(section, [])
        if expected_order and seen_by_section.get(section, []) != expected_order:
            issues.append(
                f"section '{section}' row order/content mismatch "
                f"(expected ids {len(expected_order)}, got ids {len(seen_by_section.get(section, []))})"
            )

    for section, row_ids in seen_by_section.items():
        dupes = [row_id for row_id, count in _counts(row_ids).items() if count > 1]
        if dupes:
            issues.append(f"section '{section}' has duplicate row ids: {', '.join(dupes[:5])}")

    return issues


def _counts(items: Iterable[str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    return counts
