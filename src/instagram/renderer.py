from __future__ import annotations

import hashlib
import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


CARD_BASE_WIDTH = 540
CARD_BASE_HEIGHT = 675
CARD_WIDTH = 1080
CARD_HEIGHT = 1350
PLAYWRIGHT_PKG_DEFAULT = "playwright@1.52.0"


@dataclass(frozen=True)
class RenderedSlide:
    slide_number: int
    path: Path
    width: int
    height: int


@dataclass(frozen=True)
class RenderedCarousel:
    manifest_path: Path | None
    slides: list[RenderedSlide]


def _html_escape(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _threshold_bar_from_manifest(manifest: dict[str, Any]) -> str:
    if manifest.get("variant") == "by_fixture_text_prototype":
        return "RECENT FORM DATA · PLAYER + TEAM STAT PROPS"
    thresholds = manifest.get("thresholds") or {}
    min_hit_pct = float(thresholds.get("min_hit_pct") or 0)
    min_odds = float(thresholds.get("min_odds") or 0)
    min_starts = int(thresholds.get("min_starts") or 0)
    return f"{int(round(min_hit_pct * 100))}%+ HIT RATE · ODDS >{min_odds:.2f} · MIN N={min_starts}"


def _title_words_for_manifest(manifest: dict[str, Any]) -> tuple[str, str]:
    if manifest.get("variant") == "by_fixture_text_prototype":
        return ("BY", "FIXTURE")
    if manifest.get("post_type") == "potential_value":
        return ("POTENTIAL", "VALUE")
    return ("HIGH", "PROBABILITY")


def _post_badge_for_manifest(manifest: dict[str, Any]) -> str:
    if manifest.get("variant") == "by_fixture_text_prototype":
        return "Premier League"
    return "Stats & Odds List" if manifest.get("post_type") == "potential_value" else "High Probability List"


def _date_badge(manifest: dict[str, Any]) -> str:
    fixture_dates = [str(d) for d in (manifest.get("fixture_dates") or [])]
    if not fixture_dates:
        return str(manifest.get("scheduled_for") or "")
    if len(fixture_dates) == 1:
        return fixture_dates[0]
    return f"{fixture_dates[0]} +{len(fixture_dates)-1}d"


def _slide_dots(slide: dict[str, Any]) -> str:
    total = int(slide.get("slide_count") or 0)
    active = int(slide.get("slide_number") or 1)
    dots: list[str] = []
    for i in range(1, total + 1):
        klass = "dot active" if i == active else "dot"
        dots.append(f'<div class="{klass}"></div>')
    return "".join(dots)


def _cover_featured_rows(manifest: dict[str, Any], limit: int = 8) -> list[dict[str, Any]]:
    sections = ((manifest.get("sections") or {}).get("by_section") or {})
    picks: list[dict[str, Any]] = []
    for rows in sections.values():
        for row in rows or []:
            picks.append(row)
            if len(picks) >= limit:
                return picks
    return picks


def _cover_section_counts(manifest: dict[str, Any]) -> list[tuple[str, int]]:
    counts = ((manifest.get("counts") or {}).get("by_section") or {})
    ordered: list[tuple[str, int]] = []
    for slide in list(manifest.get("slides") or []):
        if slide.get("slide_type") != "section":
            continue
        section = str(slide.get("section_label") or "")
        if not section or any(existing == section for existing, _ in ordered):
            continue
        ordered.append((section, int(counts.get(section) or 0)))
    if ordered:
        return ordered
    for section, count in counts.items():
        section_label = str(section or "")
        if section_label:
            ordered.append((section_label, int(count or 0)))
    return ordered


def _cover_intro_compact(manifest: dict[str, Any]) -> str:
    thresholds = manifest.get("thresholds") or {}
    hit_pct = int(round(float(thresholds.get("min_hit_pct") or 0) * 100))
    min_odds = float(thresholds.get("min_odds") or 0)
    min_starts = int(thresholds.get("min_starts") or 0)
    if manifest.get("variant") == "fixture_per_slide_prototype":
        return (
            f"One fixture per slide. Bet365 shot props only. "
            f"{hit_pct}%+ hit rate, odds >{min_odds:.2f}, starter-only, min n={min_starts}."
        )
    return (
        f"Bet365 shot props only. {hit_pct}%+ hit rate, odds >{min_odds:.2f}, "
        f"starter-only, min n={min_starts}."
    )


def _render_header(manifest: dict[str, Any], slide: dict[str, Any]) -> str:
    title_words = slide.get("title_words") or {}
    primary, accent = (
        str(title_words.get("primary") or _title_words_for_manifest(manifest)[0]),
        str(title_words.get("accent") or _title_words_for_manifest(manifest)[1]),
    )
    threshold_bar = str(slide.get("threshold_bar") or _threshold_bar_from_manifest(manifest))
    return f"""
    <div class="card-header">
      <div class="header-top">
        <div class="brand">THE ODDS <span>ANALYST</span></div>
        <div class="header-right">
          <div class="post-badge">{_html_escape(slide.get("post_badge") or _post_badge_for_manifest(manifest))}</div>
          <div class="date-badge">{_html_escape(_date_badge(manifest))}</div>
        </div>
      </div>
      <div class="main-title">{_html_escape(primary)} <span>{_html_escape(accent)}</span></div>
      <div class="threshold-bar">
        <div class="tline"></div>
        <div class="ttext">{_html_escape(threshold_bar)}</div>
        <div class="tline"></div>
      </div>
      <div class="slide-indicator">{_slide_dots(slide)}</div>
    </div>
    """


def _render_footer() -> str:
    return """
    <div class="card-footer">
      <div class="footer-left">Bet365 odds (current at build time) · starter-only hit rate</div>
      <div class="footer-right">@Odds_Analyst</div>
    </div>
    """


def _render_cover_body(manifest: dict[str, Any], slide: dict[str, Any]) -> str:
    stats = slide.get("stats") or {}
    fixture_window = str(slide.get("fixture_window") or "")
    fixture_meta = (
        f'<div class="cover-fixture-window">{_html_escape(fixture_window)}</div>' if fixture_window else ""
    )
    featured = _cover_featured_rows(manifest, limit=8)
    featured_markup_parts: list[str] = []
    for row in featured:
        player_name = str(row.get("player_name") or "")
        team_name = str(row.get("team_name") or "")
        stat_label = str(row.get("stat_label") or "")
        threshold = int(row.get("threshold") or 0)
        prop_label = f"{threshold}+ {stat_label}"
        featured_markup_parts.append(
            f"""
            <div class="cover-chip">
              <div class="cover-chip-text">
                <div class="cover-chip-name">{_html_escape(player_name)}</div>
                <div class="cover-chip-meta">{_html_escape(team_name)} · {_html_escape(prop_label)}</div>
              </div>
              <div class="cover-chip-hit">{_html_escape((row.get('display') or {}).get('rate') or '')}</div>
              <div class="cover-chip-odds">{_html_escape((row.get('display') or {}).get('odds') or '')}</div>
            </div>
            """
        )
    featured_markup = "".join(featured_markup_parts)
    section_count_rows = []
    for section_label, count in _cover_section_counts(manifest):
        section_count_rows.append(
            f"""
            <div class="cover-count-row">
              <div class="cover-count-label">{_html_escape(section_label)}</div>
              <div class="cover-count-value">{count}</div>
            </div>
            """
        )
    section_count_markup = "".join(section_count_rows)
    return f"""
    <div class="cover-body">
      <div class="cover-kicker">DATA SNAPSHOT</div>
      <div class="cover-desc">{_html_escape(_cover_intro_compact(manifest))}</div>
      <div class="cover-top-grid">
        <div class="cover-left">
          {fixture_meta}
          <div class="cover-stats">
            <div class="cover-stat">
              <div class="cover-stat-num">{int(stats.get("total_players") or 0)}</div>
              <div class="cover-stat-label">Qualifiers</div>
            </div>
            <div class="cover-stat">
              <div class="cover-stat-num">{int(stats.get("stat_types") or 0)}</div>
              <div class="cover-stat-label">Sections</div>
            </div>
            <div class="cover-stat">
              <div class="cover-stat-num">{int(stats.get("hit_rate_threshold_pct") or 0)}%+</div>
              <div class="cover-stat-label">Threshold</div>
            </div>
          </div>
        </div>
        <div class="cover-counts-panel">
          <div class="cover-panel-head">Rows per section</div>
          <div class="cover-count-list">{section_count_markup}</div>
        </div>
      </div>
      <div class="cover-panel cover-panel-data">
        <div class="cover-panel-head cover-panel-grid-head">
          <span>Top rows</span>
          <span>Hit</span>
          <span>Bet365</span>
        </div>
        <div class="cover-chip-list">{featured_markup or '<div class="cover-chip-empty">No rows</div>'}</div>
      </div>
      <div class="cover-disclaimer">All rows in carousel use Bet365 prices captured at generation time.</div>
    </div>
    """


def _render_section_rows(slide: dict[str, Any]) -> str:
    rows = list(slide.get("rows") or [])
    rendered: list[str] = []
    for idx, row in enumerate(rows):
        alt = " alt" if idx % 2 == 1 else ""
        display = row.get("display") or {}
        player_name = str(row.get("player_name") or "")
        team_name = str(row.get("team_name") or "")
        fixture_label = str(row.get("fixture_label") or "")
        fixture_meta = fixture_label.replace(" vs ", "  ·  ")
        stat_label = str(row.get("stat_label") or "")
        threshold = int(row.get("threshold") or 0)
        prop_label = f"{threshold}+ {stat_label}"
        rendered.append(
            f"""
    <div class="player-row{alt}">
      <div class="player-info">
        <div class="player-name">{_html_escape(player_name)}</div>
        <div class="player-meta-line">
          <span class="player-club">{_html_escape(prop_label)}</span>
          <span class="meta-sep">·</span>
          <span class="player-fixture">{_html_escape(team_name)} · {_html_escape(fixture_meta)}</span>
        </div>
      </div>
      <div class="player-hit">{_html_escape(display.get("rate"))}</div>
      <div class="player-odds">{_html_escape(display.get("odds"))}</div>
    </div>
            """
        )
    return "".join(rendered)


def _render_section_body(slide: dict[str, Any]) -> str:
    section_label = str(slide.get("section_label") or "")
    page = int(slide.get("section_page") or 1)
    pages = int(slide.get("section_pages") or 1)
    page_suffix = f" ({page}/{pages})" if pages > 1 else ""
    return f"""
    <div class="card-body">
      <div class="section-head">
        <div class="section-head-left">
          <span class="section-label">{_html_escape(section_label + page_suffix)}</span>
          <span class="section-count">{int(slide.get('section_total_rows') or 0)} rows</span>
        </div>
        <div class="section-head-right">
          <span class="section-col hit">Hit</span>
          <span class="section-col odds">Bet365</span>
        </div>
      </div>
      <div class="player-list">{_render_section_rows(slide)}</div>
    </div>
    """


def _fixture_page_suffix(slide: dict[str, Any]) -> str:
    page = int(slide.get("fixture_page") or 1)
    pages = int(slide.get("fixture_pages") or 1)
    return f" · page {page}/{pages}" if pages > 1 else ""


def _render_fixture_count_chips(slide: dict[str, Any]) -> str:
    counts = slide.get("section_counts") or {}
    ordered = sorted(counts.items(), key=lambda item: (-int(item[1] or 0), str(item[0] or "")))
    chips: list[str] = []
    for label, count in ordered:
        chips.append(
            f"""
            <div class="fixture-chip">
              <span class="fixture-chip-label">{_html_escape(label)}</span>
              <span class="fixture-chip-value">{int(count or 0)}</span>
            </div>
            """
        )
    return "".join(chips)


def _render_fixture_rows(slide: dict[str, Any]) -> str:
    rows = list(slide.get("rows") or [])
    rendered: list[str] = []
    for idx, row in enumerate(rows):
        alt = " alt" if idx % 2 == 1 else ""
        display = row.get("display") or {}
        rendered.append(
            f"""
    <div class="fixture-row{alt}">
      <div class="fixture-player">
        <div class="fixture-player-name">{_html_escape(row.get("player_name"))}</div>
        <div class="fixture-player-team">{_html_escape(row.get("team_name"))}</div>
      </div>
      <div class="fixture-prop">{_html_escape(row.get("stat_label"))}</div>
      <div class="fixture-hit">{_html_escape(display.get("rate"))}</div>
      <div class="fixture-odds">{_html_escape(display.get("odds"))}</div>
    </div>
            """
        )
    return "".join(rendered)


def _render_fixture_body(slide: dict[str, Any]) -> str:
    fixture_index = int(slide.get("fixture_index") or 1)
    fixture_count = int(slide.get("fixture_count") or 1)
    fixture_rows = int(slide.get("fixture_row_count") or 0)
    page_suffix = _fixture_page_suffix(slide)
    return f"""
    <div class="fixture-body">
      <div class="fixture-hero">
        <div class="fixture-kicker">Fixture {fixture_index}/{fixture_count}{_html_escape(page_suffix)}</div>
        <div class="fixture-title">{_html_escape(slide.get("fixture_label"))}</div>
        <div class="fixture-meta">
          {_html_escape(slide.get("league_name"))} · {fixture_rows} qualifying props
        </div>
        <div class="fixture-chip-list">{_render_fixture_count_chips(slide)}</div>
      </div>
      <div class="fixture-table-head">
        <span>Player</span>
        <span>Prop</span>
        <span>Hit</span>
        <span>Bet365</span>
      </div>
      <div class="fixture-list">{_render_fixture_rows(slide)}</div>
    </div>
    """


def _render_fixture_sheet_rows(slide: dict[str, Any]) -> str:
    rows = list(slide.get("rows") or [])
    parts: list[str] = []
    for idx, row in enumerate(rows):
        alt = " alt" if idx % 2 == 1 else ""
        parts.append(
            f"""
    <div class="fixture-sheet-row{alt}">
      <div class="fixture-sheet-label">{_html_escape(row.get("label"))}</div>
      <div class="fixture-sheet-record">{_html_escape(row.get("record"))}</div>
    </div>
            """
        )
    return "".join(parts)


def _render_fixture_sheet_body(manifest: dict[str, Any], slide: dict[str, Any]) -> str:
    intro = str(slide.get("subtitle") or manifest.get("subtitle") or "")
    fixture_index = int(slide.get("fixture_index") or 1)
    fixture_count = int(slide.get("fixture_count") or 1)
    return f"""
    <div class="fixture-sheet-body">
      <div class="fixture-sheet-hero">
        <div class="fixture-sheet-kicker">Fixture {fixture_index}/{fixture_count}</div>
        <div class="fixture-sheet-title">{_html_escape(slide.get("header"))}</div>
        <div class="fixture-sheet-subtitle">{_html_escape(intro)}</div>
      </div>
      <div class="fixture-sheet-list">{_render_fixture_sheet_rows(slide)}</div>
    </div>
    """


def _asset_src(payload: dict[str, Any] | None, *keys: str) -> str:
    if not isinstance(payload, dict):
        return ""
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    return ""


def _hex_to_rgba(hex_color: str, alpha: float) -> str:
    color = hex_color.strip().lstrip("#")
    if len(color) != 6:
        return f"rgba(245,197,24,{alpha})"
    red = int(color[0:2], 16)
    green = int(color[2:4], 16)
    blue = int(color[4:6], 16)
    return f"rgba({red},{green},{blue},{alpha})"


def _initials(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return "?"
    parts = [part for part in text.split() if part]
    if len(parts) == 1:
        return parts[0][:1].upper()
    return (parts[0][:1] + parts[-1][:1]).upper()


def _render_media(
    *,
    src: str,
    fallback_text: str,
    accent_color: str,
    class_name: str,
    img_class: str,
) -> str:
    if src:
        return (
            f'<div class="{class_name}" style="--accent:{_html_escape(accent_color)}">'
            f'<img class="{img_class}" src="{_html_escape(src)}" alt="{_html_escape(fallback_text)}">'
            "</div>"
        )
    return (
        f'<div class="{class_name} media-fallback" style="--accent:{_html_escape(accent_color)}">'
        f"<span>{_html_escape(fallback_text)}</span>"
        "</div>"
    )


def _render_rich_team_badge(team: dict[str, Any]) -> str:
    display_name = str(team.get("display_name") or team.get("name") or "")
    accent = str(team.get("accent_color") or "#F5C518")
    src = _asset_src(team, "badge_uri", "badge_url")
    return _render_media(
        src=src,
        fallback_text=_initials(display_name),
        accent_color=accent,
        class_name="team-badge",
        img_class="team-badge-img",
    )


def _render_rich_row_icon(row: dict[str, Any], accent_color: str) -> str:
    assets = dict(row.get("assets") or {})
    is_team_row = str(row.get("subject_type") or "") == "team"
    src = (
        _asset_src(assets, "team_badge_uri", "team_badge_url")
        if is_team_row
        else _asset_src(assets, "player_face_uri", "player_face_url", "team_badge_uri", "team_badge_url")
    )
    return _render_media(
        src=src,
        fallback_text=_initials(row.get("subject_display") or row.get("subject_name")),
        accent_color=accent_color,
        class_name="row-icon",
        img_class="row-icon-img",
    )


def _render_rich_row_face(row: dict[str, Any], accent_color: str) -> str:
    assets = dict(row.get("assets") or {})
    is_team_row = str(row.get("subject_type") or "") == "team"
    src = (
        _asset_src(assets, "team_badge_uri", "team_badge_url")
        if is_team_row
        else _asset_src(assets, "player_face_uri", "player_face_url", "team_badge_uri", "team_badge_url")
    )
    fallback = row.get("subject_display") or row.get("subject_name")
    return _render_media(
        src=src,
        fallback_text=_initials(fallback),
        accent_color=accent_color,
        class_name="row-face",
        img_class="row-face-img",
    )


def _render_rich_row_badge(row: dict[str, Any], accent_color: str) -> str:
    assets = dict(row.get("assets") or {})
    src = _asset_src(assets, "team_badge_uri", "team_badge_url")
    fallback = row.get("team_name") or row.get("subject_display") or row.get("subject_name")
    return _render_media(
        src=src,
        fallback_text=_initials(fallback),
        accent_color=accent_color,
        class_name="row-badge",
        img_class="row-badge-img",
    )


def _render_rich_section(section: dict[str, Any]) -> str:
    color = str(section.get("color") or "#F5C518")
    rows = list(section.get("rows") or [])
    visual_rows = max(1, (len(rows) + 1) // 2)
    section_style = (
        f"--section-flex:{visual_rows};"
        f"--section-color:{color};"
        f"--section-surface:{_hex_to_rgba(color, 0.09)};"
        f"--section-surface-strong:{_hex_to_rgba(color, 0.14)};"
        f"--section-border:{_hex_to_rgba(color, 0.22)};"
        f"--section-rule:{_hex_to_rgba(color, 0.80)};"
        f"--section-fill:{_hex_to_rgba(color, 0.16)};"
        f"--section-fill-fade:{_hex_to_rgba(color, 0.03)};"
        f"--section-pill-bg:{_hex_to_rgba(color, 0.16)};"
        f"--section-pill-border:{_hex_to_rgba(color, 0.38)};"
    )
    rows_markup: list[str] = []
    for row in rows:
        hit_rate = float(row.get("hit_rate") or 0.0)
        bar_opacity = 0.05
        if hit_rate >= 0.95:
            bar_opacity = 0.10
        elif hit_rate >= 0.90:
            bar_opacity = 0.08
        elif hit_rate >= 0.85:
            bar_opacity = 0.07
        market_display = str(row.get("market_display") or "").strip()
        subject_display = str(row.get("subject_display") or "")
        record_display = str(row.get("record") or "")
        market_class = "stat-market stat-market-tight" if len(market_display) >= 13 else "stat-market"
        rows_markup.append(
            f"""
            <div class="stat-row">
              <div class="bar-fill" style="opacity:{bar_opacity:.2f};width:{int(row.get('bar_pct') or 0)}%"></div>
              {_render_rich_row_face(row, color)}
              <div class="stat-player">{_html_escape(subject_display)}</div>
              {_render_rich_row_badge(row, color)}
              <div class="{market_class}">{_html_escape(market_display)}</div>
              <div class="stat-record">
                <span class="stat-record-label">won in</span>
                <span class="stat-record-value">{_html_escape(record_display)}</span>
              </div>
            </div>
            """
        )
    return f"""
    <div class="section" style="{section_style}">
      <div class="section-head">
        <div class="section-title">{_html_escape(section.get("title"))}</div>
        <div class="section-rule"></div>
      </div>
      <div class="rows-grid">
        {''.join(rows_markup)}
      </div>
    </div>
    """


def _render_rich_slide(markup_title: str, manifest: dict[str, Any], slide: dict[str, Any]) -> str:
    home_team = dict(slide.get("home_team") or {})
    away_team = dict(slide.get("away_team") or {})
    sections_html = "".join(_render_rich_section(section) for section in list(slide.get("sections") or []))
    density = str(slide.get("density") or "default")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_html_escape(markup_title)}</title>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@400;500;600;700&family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #0b0f14;
    --surface: #0f1620;
    --surface-elevated: #141c27;
    --border: #1f2a37;
    --gold: #f5a524;
    --brand-orange: #ef6a29;
    --text: #f8fafc;
    --muted: #94a3b8;
  }}
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{
    width: {CARD_WIDTH}px;
    height: {CARD_HEIGHT}px;
    overflow: hidden;
    background: #070b11;
  }}
  body {{
    display: flex;
    align-items: flex-start;
    justify-content: flex-start;
    font-family: 'IBM Plex Sans', sans-serif;
    font-variant-numeric: tabular-nums;
  }}
  body.ready::after {{ content: ''; }}
  .canvas {{
    width: {CARD_WIDTH}px;
    height: {CARD_HEIGHT}px;
    overflow: hidden;
    background: #070b11;
  }}
  .scale {{
    width: {CARD_BASE_WIDTH}px;
    height: {CARD_BASE_HEIGHT}px;
    transform: scale(2);
    transform-origin: top left;
  }}
  .card {{
    width: {CARD_BASE_WIDTH}px;
    height: {CARD_BASE_HEIGHT}px;
    background: var(--bg);
    position: relative;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    border: 1px solid var(--border);
    box-shadow: 0 16px 40px rgba(3, 7, 18, 0.42);
  }}
  .card::after {{
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--brand-orange) 12%, var(--gold) 46%, var(--brand-orange) 88%, transparent);
    z-index: 10;
  }}
  .card::before {{
    content: '';
    position: absolute;
    inset: 0;
    background:
      radial-gradient(circle at top left, rgba(245,165,36,0.06), transparent 34%),
      radial-gradient(circle at top right, rgba(239,106,41,0.08), transparent 32%);
    pointer-events: none;
    z-index: 0;
  }}
  .header {{
    padding: 8px 15px 6px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
    z-index: 2;
    position: relative;
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: linear-gradient(180deg, rgba(20,28,39,0.96), rgba(11,15,20,0.92));
  }}
  .brand {{ display: flex; align-items: center; gap: 6px; }}
  .brand-mark {{
    width: 13px;
    height: 13px;
    border-radius: 4px;
    background: linear-gradient(135deg, var(--gold), var(--brand-orange));
    box-shadow: 0 0 14px rgba(245,165,36,0.22);
    position: relative;
    transform: rotate(12deg);
  }}
  .brand-mark::after {{
    content: '';
    position: absolute;
    inset: 3px;
    border-radius: 2px;
    background: rgba(11,15,20,0.72);
  }}
  .brand-name {{
    font-family: 'Sora', sans-serif;
    font-size: 10.5px;
    font-weight: 600;
    letter-spacing: 0.18em;
    color: var(--text);
    text-transform: uppercase;
  }}
  .header-right {{ display: flex; align-items: center; gap: 8px; }}
  .league-pill {{
    background: linear-gradient(135deg, var(--gold), #f2a10f);
    color: #081018;
    font-size: 7px;
    font-weight: 700;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    padding: 3px 8px;
    border-radius: 999px;
    box-shadow: 0 6px 14px rgba(245,165,36,0.18);
  }}
  .date-text {{
    font-size: 7.8px;
    color: var(--muted);
    font-family: 'IBM Plex Mono', monospace;
  }}
  .fixture-hero {{
    padding: 6px 16px 5px;
    border-bottom: 1px solid var(--border);
    flex-shrink: 0;
    z-index: 2;
    position: relative;
    background: linear-gradient(180deg, rgba(20,28,39,0.96) 0%, rgba(11,15,20,0.88) 100%);
    text-align: center;
  }}
  .fixture-num {{
    font-family: 'IBM Plex Mono', monospace;
    font-size: 7px;
    font-weight: 500;
    letter-spacing: 0.16em;
    color: var(--gold);
    text-transform: uppercase;
    opacity: 0.82;
    margin-bottom: 2px;
  }}
  .teams-line {{
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 7px;
    margin-bottom: 1px;
  }}
  .team-badge {{
    width: 20px;
    height: 20px;
    border-radius: 50%;
    background: radial-gradient(circle at 30% 30%, rgba(255,255,255,0.22), rgba(255,255,255,0.04));
    box-shadow: 0 0 8px color-mix(in srgb, var(--accent) 45%, transparent);
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    border: 1px solid rgba(255,255,255,0.18);
  }}
  .team-badge-img {{
    width: 90%;
    height: 90%;
    object-fit: contain;
  }}
  .media-fallback {{
    background: linear-gradient(135deg, color-mix(in srgb, var(--accent) 20%, #121726), #0b1020);
    color: #ffffff;
    font-family: 'DM Mono', monospace;
    font-size: 8px;
    font-weight: 700;
  }}
  .teams-name {{
    font-family: 'Sora', sans-serif;
    font-size: 20px;
    font-weight: 700;
    letter-spacing: -0.03em;
    color: var(--text);
    line-height: 1.05;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .teams-name .vs {{
    color: rgba(148,163,184,0.88);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 12px;
    margin: 0 5px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }}
  .kickoff-label {{
    font-size: 8px;
    font-weight: 500;
    letter-spacing: 0.05em;
    color: var(--muted);
    text-transform: uppercase;
  }}
  .kickoff-label span {{ color: var(--gold); }}
  .dots {{
    display: flex;
    justify-content: center;
    gap: 6px;
    padding: 5px 0 4px;
    flex-shrink: 0;
    z-index: 2;
    position: relative;
  }}
  .dot {{
    height: 3px;
    width: 18px;
    border-radius: 999px;
    background: rgba(148,163,184,0.28);
    box-shadow: inset 0 0 0 1px rgba(148,163,184,0.12);
  }}
  .dot.active {{
    background: linear-gradient(90deg, var(--brand-orange), var(--gold));
    width: 28px;
    box-shadow: 0 0 12px rgba(245,165,36,0.32);
  }}
  .body {{
    flex: 1;
    padding: 2px 8px 1px;
    z-index: 2;
    position: relative;
    overflow: hidden;
    display: flex;
    flex-direction: column;
    gap: 4px;
    min-height: 0;
  }}
  .section {{
    display: grid;
    grid-template-rows: auto 1fr;
    gap: 1px;
    flex: var(--section-flex) 1 0;
    min-height: 0;
  }}
  .section-head {{
    display: flex;
    align-items: center;
    gap: 6px;
    padding: 0 4px 1px;
    background: linear-gradient(90deg, var(--section-surface-strong), rgba(11,15,20,0));
    border-radius: 2px;
  }}
  .section-title {{
    font-family: 'Sora', sans-serif;
    font-size: 8.3px;
    font-weight: 700;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    white-space: nowrap;
    color: var(--section-color);
    text-shadow: 0 0 8px color-mix(in srgb, var(--section-color) 28%, transparent);
  }}
  .section-rule {{
    flex: 1;
    height: 1px;
    background: linear-gradient(90deg, var(--section-rule), rgba(255,255,255,0.06));
  }}
  .rows-grid {{
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1px 4px;
    min-height: 0;
    height: 100%;
    align-content: stretch;
    grid-auto-rows: minmax(0, 1fr);
  }}
  .stat-row {{
    display: grid;
    grid-template-columns: 24px minmax(0, 1.10fr) 16px minmax(0, 1.34fr) auto;
    gap: 4px;
    align-items: center;
    min-height: 0;
    padding: 3px 6px;
    border-radius: 2px;
    position: relative;
    overflow: hidden;
    background: linear-gradient(90deg, color-mix(in srgb, var(--section-surface) 92%, var(--surface-elevated)), rgba(20,28,39,0.72) 72%);
    border: 1px solid var(--section-border);
  }}
  .stat-row::before {{
    content: '';
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    width: 2px;
    background: var(--section-color);
    opacity: 0.95;
  }}
  .bar-fill {{
    position: absolute;
    left: 0;
    top: 0;
    bottom: 0;
    border-radius: 2px;
    pointer-events: none;
    background: linear-gradient(90deg, var(--section-fill), var(--section-fill-fade));
  }}
  .row-face,
  .row-badge {{
    overflow: hidden;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    z-index: 1;
    border: 1px solid rgba(255,255,255,0.14);
    flex-shrink: 0;
  }}
  .row-face {{
    width: 24px;
    height: 24px;
    border-radius: 50%;
  }}
  .row-badge {{
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: rgba(255,255,255,0.03);
  }}
  .row-face-img,
  .row-badge-img {{
    width: 100%;
    height: 100%;
  }}
  .row-face-img {{
    object-fit: cover;
  }}
  .row-badge-img {{
    object-fit: contain;
    width: 88%;
    height: 88%;
  }}
  .stat-player {{
    min-width: 0;
    position: relative;
    z-index: 1;
    font-size: 10.7px;
    font-weight: 700;
    color: var(--text);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1;
    text-shadow: 0 1px 0 rgba(0,0,0,0.35);
  }}
  .stat-market {{
    min-width: 0;
    position: relative;
    z-index: 1;
    font-size: 10.9px;
    font-weight: 700;
    color: #ffffff;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1;
    text-shadow: 0 1px 0 rgba(0,0,0,0.38);
  }}
  .stat-market-tight {{
    font-size: 9.9px;
  }}
  .stat-record {{
    display: inline-flex;
    align-items: center;
    gap: 3px;
    font-family: 'IBM Plex Mono', monospace;
    position: relative;
    z-index: 1;
    border: 1px solid var(--section-pill-border);
    border-radius: 999px;
    padding: 2px 5px;
    white-space: nowrap;
    justify-self: end;
    background: var(--section-pill-bg);
  }}
  .stat-record-label {{
    font-size: 6.4px;
    font-weight: 500;
    color: #b8c1dc;
    letter-spacing: 0.02em;
  }}
  .stat-record-value {{
    font-size: 9px;
    font-weight: 700;
    letter-spacing: -0.3px;
    color: var(--section-color);
  }}
  .footer {{
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding: 4px 16px 6px;
    border-top: 1px solid var(--border);
    flex-shrink: 0;
    z-index: 2;
    position: relative;
    background: linear-gradient(180deg, rgba(11,15,20,0.78), rgba(15,22,32,0.96));
  }}
  .footer-left {{
    font-size: 7.2px;
    font-weight: 600;
    letter-spacing: 0.07em;
    color: var(--muted);
    text-transform: uppercase;
    line-height: 1.3;
    opacity: 0.92;
  }}
  .footer-handle {{
    font-family: 'Sora', sans-serif;
    font-size: 10.8px;
    font-weight: 600;
    letter-spacing: 0.12em;
    color: var(--gold);
    text-transform: uppercase;
  }}
  .card.density-dense .stat-row {{
    min-height: 0;
    padding: 2px 5px;
    gap: 4px;
  }}
  .card.density-dense .stat-player {{
    font-size: 9.3px;
  }}
  .card.density-dense .stat-market {{
    font-size: 9.5px;
  }}
  .card.density-dense .stat-market-tight {{
    font-size: 9px;
  }}
  .card.density-dense .stat-record {{
    gap: 2px;
    padding: 2px 4px;
  }}
  .card.density-dense .stat-record-label {{
    font-size: 6px;
  }}
  .card.density-dense .stat-record-value {{
    font-size: 8.3px;
  }}
  .card.density-dense .row-face {{
    width: 20px;
    height: 20px;
  }}
  .card.density-dense .row-badge {{
    width: 14px;
    height: 14px;
  }}
  .card.density-xdense .stat-row {{
    min-height: 0;
    padding: 2px 4px;
    gap: 3px;
  }}
  .card.density-xdense .stat-player {{
    font-size: 8.4px;
  }}
  .card.density-xdense .stat-market {{
    font-size: 8.8px;
  }}
  .card.density-xdense .stat-market-tight {{
    font-size: 8.2px;
  }}
  .card.density-xdense .stat-record {{
    gap: 2px;
    padding: 2px 4px;
  }}
  .card.density-xdense .stat-record-label {{
    font-size: 5.6px;
  }}
  .card.density-xdense .stat-record-value {{
    font-size: 7.8px;
  }}
  .card.density-xdense .row-face {{
    width: 18px;
    height: 18px;
  }}
  .card.density-xdense .row-badge {{
    width: 13px;
    height: 13px;
  }}
</style>
</head>
<body>
<div class="canvas">
  <div class="scale">
    <div class="card density-{_html_escape(density)}">
      <div class="header">
        <div class="brand">
          <div class="brand-mark"></div>
          <div class="brand-name">Odds Searcher</div>
        </div>
        <div class="header-right">
          <div class="league-pill">Premier League</div>
          <div class="date-text">{_html_escape(slide.get("date_badge") or manifest.get("scheduled_for") or "")}</div>
        </div>
      </div>
      <div class="fixture-hero">
        <div class="fixture-num">Fixture {int(slide.get("fixture_index") or 1)} / {int(slide.get("fixture_count") or 1)}</div>
        <div class="teams-line">
          {_render_rich_team_badge(home_team)}
          <div class="teams-name">{_html_escape(home_team.get("display_name"))} <span class="vs">vs</span> {_html_escape(away_team.get("display_name"))}</div>
          {_render_rich_team_badge(away_team)}
        </div>
        <div class="kickoff-label">Kickoff <span>{_html_escape(slide.get("kickoff_label"))}</span></div>
      </div>
      <div class="dots">{_slide_dots(slide)}</div>
      <div class="body">{sections_html}</div>
      <div class="footer">
        <div class="footer-left">Recent form snapshot · starter-only hit rate</div>
        <div class="footer-handle">oddssearch.io</div>
      </div>
    </div>
  </div>
</div>
<script>
  const waitFonts = Promise.resolve(document.fonts && document.fonts.ready ? document.fonts.ready : null)
    .catch(() => null);
  const waitImages = Promise.all(
    Array.from(document.images || []).map((img) => {{
      if (img.complete) return Promise.resolve();
      return new Promise((resolve) => {{
        img.addEventListener('load', resolve, {{ once: true }});
        img.addEventListener('error', resolve, {{ once: true }});
      }});
    }})
  ).catch(() => null);
  Promise.all([waitFonts, waitImages]).finally(() => document.body.classList.add('ready'));
</script>
</body>
</html>
"""


def _build_slide_markup(manifest: dict[str, Any], slide: dict[str, Any]) -> str:
    slide_type = slide.get("slide_type")
    if slide_type == "cover":
        body_markup = _render_cover_body(manifest, slide)
    elif slide_type == "fixture_sheet":
        body_markup = _render_fixture_sheet_body(manifest, slide)
    elif slide_type == "fixture":
        body_markup = _render_fixture_body(slide)
    else:
        body_markup = _render_section_body(slide)
    return _render_header(manifest, slide) + body_markup + _render_footer()


def _slide_html_document(manifest: dict[str, Any], slide: dict[str, Any]) -> str:
    title = f"{manifest.get('post_type')} slide {slide.get('slide_number')}"
    if manifest.get("variant") == "by_fixture_rich_prototype":
        return _render_rich_slide(title, manifest, slide)
    card_markup = _build_slide_markup(manifest, slide)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{_html_escape(title)}</title>
<link href="https://fonts.googleapis.com/css2?family=Bebas+Neue&family=Barlow+Condensed:wght@400;500;600;700;800&family=DM+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  html, body {{
    width: {CARD_WIDTH}px;
    height: {CARD_HEIGHT}px;
    overflow: hidden;
    background: #030508;
  }}
  body {{
    display: flex;
    align-items: flex-start;
    justify-content: flex-start;
    font-family: 'Barlow Condensed', sans-serif;
  }}
  body.ready::after {{ content: ''; }}
  .canvas {{
    width: {CARD_WIDTH}px;
    height: {CARD_HEIGHT}px;
    overflow: hidden;
    background: #030508;
  }}
  .scale {{
    width: {CARD_BASE_WIDTH}px;
    height: {CARD_BASE_HEIGHT}px;
    transform: scale(2);
    transform-origin: top left;
  }}
  .card {{
    width: {CARD_BASE_WIDTH}px;
    height: {CARD_BASE_HEIGHT}px;
    background: #0d0f1a;
    overflow: hidden;
    position: relative;
    display: flex;
    flex-direction: column;
  }}
  .corner {{
    display: none;
  }}
  .corner.tr {{ top: -18px; right: -18px; }}
  .corner.bl {{ bottom: -18px; left: -18px; }}
  .card-header {{
    padding: 14px 20px 10px;
    border-bottom: 1px solid #f5c518;
    position: relative;
    z-index: 1;
    flex-shrink: 0;
    background: linear-gradient(180deg, #0e1221 0%, #0a0f1b 100%);
  }}
  .header-top {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 6px;
  }}
  .brand {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 11px;
    letter-spacing: 0.14em;
    color: #7f88ad;
  }}
  .brand span {{ color: #F5C518; opacity: 1; }}
  .header-right {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .post-badge {{
    font-size: 8px;
    font-weight: 700;
    letter-spacing: 0.12em;
    color: #0d0f1a;
    background: #F5C518;
    padding: 2px 7px;
    border-radius: 2px;
    text-transform: uppercase;
  }}
  .date-badge {{
    font-family: 'DM Mono', monospace;
    font-size: 8px;
    color: #c5cce8;
    opacity: 0.75;
  }}
  .main-title {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 36px;
    letter-spacing: 0.045em;
    color: #fff;
    line-height: 0.92;
    margin-bottom: 5px;
  }}
  .main-title span {{ color: #F5C518; }}
  .threshold-bar {{
    display: flex;
    align-items: center;
    gap: 6px;
  }}
  .tline {{ flex: 1; height: 1px; background: #f5c518; opacity: 0.2; }}
  .ttext {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 11px;
    letter-spacing: 0.09em;
    color: #F5C518;
    opacity: 0.95;
    white-space: nowrap;
  }}
  .slide-indicator {{
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 4px;
    margin-top: 5px;
  }}
  .dot {{
    width: 5px;
    height: 5px;
    border-radius: 50%;
    background: #2a2d40;
  }}
  .dot.active {{
    background: #F5C518;
    width: 14px;
    border-radius: 3px;
  }}
  .card-body {{
    flex: 1;
    overflow: hidden;
    position: relative;
    z-index: 1;
    display: flex;
    flex-direction: column;
  }}
  .section-head {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #0c1020;
    border-bottom: 1px solid #202742;
    padding: 7px 16px 7px 18px;
    flex-shrink: 0;
  }}
  .section-head-left {{
    display: flex;
    align-items: baseline;
    gap: 8px;
    min-width: 0;
  }}
  .section-label {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 16px;
    letter-spacing: 0.08em;
    color: #F5C518;
  }}
  .section-count {{
    font-family: 'DM Mono', monospace;
    font-size: 8px;
    color: #c2caea;
    opacity: 0.7;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }}
  .section-head-right {{
    display: grid;
    grid-template-columns: 50px 58px;
    gap: 6px;
    align-items: center;
    flex-shrink: 0;
  }}
  .section-col {{
    font-family: 'DM Mono', monospace;
    font-size: 7px;
    color: #ffffff;
    opacity: 0.7;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    text-align: right;
  }}
  .section-col.odds {{
    text-align: center;
    color: #f5c518;
    opacity: 0.95;
  }}
  .player-list {{ flex: 1; overflow: hidden; }}
  .player-row {{
    display: flex;
    align-items: center;
    padding: 0 10px 0 12px;
    height: 38px;
    border-bottom: 1px solid #131a2d;
    background: #0b0f1b;
  }}
  .player-row.alt {{
    background: #0a0e18;
  }}
  .player-info {{ flex: 1; min-width: 0; display: flex; flex-direction: column; justify-content: center; }}
  .player-name {{
    font-size: 11px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: 0.01em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1;
  }}
  .player-meta-line {{
    display: flex;
    align-items: center;
    gap: 4px;
    min-width: 0;
    margin-top: 1px;
  }}
  .player-club {{
    font-size: 7px;
    font-weight: 700;
    color: #f5c518;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    flex-shrink: 0;
  }}
  .meta-sep {{
    font-family: 'DM Mono', monospace;
    font-size: 8px;
    color: #7e87ab;
    flex-shrink: 0;
  }}
  .player-fixture {{
    font-family: 'DM Mono', monospace;
    font-size: 7px;
    color: #ffffff;
    opacity: 0.58;
    letter-spacing: 0.02em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
    flex: 1;
  }}
  .player-hit {{
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    color: #ffffff;
    text-align: right;
    width: 50px;
    min-width: 50px;
    margin-left: 8px;
    letter-spacing: 0.01em;
  }}
  .player-odds {{
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    font-weight: 600;
    color: #0a0d16;
    background: linear-gradient(180deg, #ffde5d 0%, #f5c518 100%);
    border: 1px solid rgba(255,255,255,0.2);
    padding: 3px 6px;
    border-radius: 4px;
    width: 58px;
    min-width: 58px;
    text-align: center;
  }}
  .fixture-body {{
    flex: 1;
    display: flex;
    flex-direction: column;
    padding: 10px 14px 10px;
    gap: 8px;
    overflow: hidden;
  }}
  .fixture-hero {{
    border: 1px solid #263050;
    background: linear-gradient(180deg, #101628 0%, #0b1020 100%);
    border-radius: 8px;
    padding: 10px 12px 9px;
    display: flex;
    flex-direction: column;
    gap: 5px;
  }}
  .fixture-kicker {{
    font-family: 'DM Mono', monospace;
    font-size: 8px;
    color: #cfd5ee;
    opacity: 0.82;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }}
  .fixture-title {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 24px;
    line-height: 0.95;
    letter-spacing: 0.04em;
    color: #ffffff;
  }}
  .fixture-meta {{
    font-family: 'DM Mono', monospace;
    font-size: 8px;
    color: #f5c518;
    opacity: 0.95;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }}
  .fixture-chip-list {{
    display: flex;
    flex-wrap: wrap;
    gap: 5px;
    margin-top: 1px;
  }}
  .fixture-chip {{
    display: inline-flex;
    align-items: center;
    gap: 6px;
    padding: 4px 6px;
    border-radius: 999px;
    background: #0a0f1b;
    border: 1px solid #1f2742;
  }}
  .fixture-chip-label {{
    font-family: 'DM Mono', monospace;
    font-size: 7px;
    color: #ffffff;
    opacity: 0.78;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }}
  .fixture-chip-value {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 12px;
    color: #f5c518;
    line-height: 1;
  }}
  .fixture-table-head {{
    display: grid;
    grid-template-columns: minmax(0, 1.45fr) minmax(0, 0.8fr) 48px 58px;
    gap: 6px;
    align-items: center;
    padding: 0 6px;
    font-family: 'DM Mono', monospace;
    font-size: 7px;
    color: #ffffff;
    opacity: 0.7;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }}
  .fixture-table-head span:nth-child(3),
  .fixture-table-head span:nth-child(4) {{
    text-align: right;
  }}
  .fixture-table-head span:nth-child(4) {{
    color: #f5c518;
    opacity: 0.95;
  }}
  .fixture-list {{
    flex: 1;
    overflow: hidden;
    border: 1px solid #1b243d;
    border-radius: 8px;
    background: #090d18;
  }}
  .fixture-row {{
    display: grid;
    grid-template-columns: minmax(0, 1.45fr) minmax(0, 0.8fr) 48px 58px;
    gap: 6px;
    align-items: center;
    padding: 0 10px;
    min-height: 44px;
    border-bottom: 1px solid #141b2f;
    background: #0b0f1b;
  }}
  .fixture-row.alt {{
    background: #090d18;
  }}
  .fixture-row:last-child {{
    border-bottom: 0;
  }}
  .fixture-player {{
    min-width: 0;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }}
  .fixture-player-name {{
    font-size: 11px;
    font-weight: 700;
    color: #ffffff;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1.05;
  }}
  .fixture-player-team {{
    font-family: 'DM Mono', monospace;
    font-size: 7px;
    color: #cfd5ee;
    opacity: 0.7;
    margin-top: 2px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }}
  .fixture-prop {{
    font-size: 9px;
    font-weight: 700;
    color: #f5c518;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .fixture-hit {{
    font-family: 'DM Mono', monospace;
    font-size: 9px;
    color: #ffffff;
    text-align: right;
  }}
  .fixture-odds {{
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    font-weight: 600;
    color: #0a0d16;
    background: linear-gradient(180deg, #ffde5d 0%, #f5c518 100%);
    border: 1px solid rgba(255,255,255,0.2);
    padding: 3px 6px;
    border-radius: 4px;
    width: 58px;
    min-width: 58px;
    text-align: center;
    justify-self: end;
  }}
  .fixture-sheet-body {{
    flex: 1;
    display: flex;
    flex-direction: column;
    padding: 10px 14px 10px;
    gap: 8px;
    overflow: hidden;
  }}
  .fixture-sheet-hero {{
    border: 1px solid #263050;
    background: linear-gradient(180deg, #101628 0%, #0b1020 100%);
    border-radius: 8px;
    padding: 9px 10px 8px;
    display: flex;
    flex-direction: column;
    gap: 4px;
  }}
  .fixture-sheet-kicker {{
    font-family: 'DM Mono', monospace;
    font-size: 8px;
    color: #f5c518;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }}
  .fixture-sheet-title {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 22px;
    line-height: 0.95;
    letter-spacing: 0.04em;
    color: #ffffff;
  }}
  .fixture-sheet-subtitle {{
    font-family: 'DM Mono', monospace;
    font-size: 7px;
    color: #cfd5ee;
    opacity: 0.75;
    letter-spacing: 0.03em;
    line-height: 1.3;
  }}
  .fixture-sheet-list {{
    flex: 1;
    overflow: hidden;
    border: 1px solid #1b243d;
    border-radius: 8px;
    background: #090d18;
    display: flex;
    flex-direction: column;
  }}
  .fixture-sheet-row {{
    display: grid;
    grid-template-columns: minmax(0, 1fr) 62px;
    gap: 8px;
    align-items: center;
    padding: 0 9px;
    min-height: 22px;
    border-bottom: 1px solid #131a2d;
    background: #0b0f1b;
  }}
  .fixture-sheet-row.alt {{
    background: #090d18;
  }}
  .fixture-sheet-row:last-child {{
    border-bottom: 0;
  }}
  .fixture-sheet-label {{
    font-size: 8px;
    font-weight: 600;
    color: #ffffff;
    line-height: 1.15;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .fixture-sheet-record {{
    font-family: 'DM Mono', monospace;
    font-size: 8px;
    font-weight: 700;
    color: #f5c518;
    text-align: right;
    letter-spacing: 0.02em;
    white-space: nowrap;
  }}
  .cover-body {{
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: stretch;
    justify-content: flex-start;
    padding: 12px 18px 10px;
    gap: 8px;
    position: relative;
    z-index: 1;
    text-align: left;
  }}
  .cover-kicker {{
    font-family: 'DM Mono', monospace;
    font-size: 9px;
    letter-spacing: 0.12em;
    color: #d1d7ef;
    opacity: 0.9;
    text-transform: uppercase;
  }}
  .cover-desc {{
    font-family: 'DM Mono', monospace;
    font-size: 9px;
    font-weight: 500;
    color: #ffffff;
    opacity: 0.78;
    text-align: left;
    letter-spacing: 0.03em;
    line-height: 1.35;
    max-width: none;
  }}
  .cover-top-grid {{
    display: grid;
    grid-template-columns: 1.2fr 0.9fr;
    gap: 8px;
    align-items: stretch;
  }}
  .cover-left {{
    display: flex;
    flex-direction: column;
    gap: 7px;
  }}
  .cover-fixture-window {{
    font-family: 'DM Mono', monospace;
    font-size: 9px;
    color: #ffffff;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    border: 1px solid #263050;
    background: #101628;
    padding: 6px 8px;
    border-radius: 4px;
    align-self: stretch;
  }}
  .cover-stats {{
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 6px;
    margin-top: 0;
  }}
  .cover-stat {{
    background: #101628;
    border: 1px solid #263050;
    border-radius: 6px;
    padding: 7px 6px 6px;
    text-align: center;
    min-width: 0;
  }}
  .cover-stat-num {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 22px;
    color: #ffffff;
    letter-spacing: 0.04em;
    line-height: 1;
  }}
  .cover-stat-label {{
    font-size: 8px;
    font-weight: 600;
    color: #f5c518;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-top: 2px;
  }}
  .cover-counts-panel {{
    border: 1px solid #263050;
    background: #0f1526;
    border-radius: 6px;
    padding: 7px 8px;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }}
  .cover-count-list {{
    display: flex;
    flex-direction: column;
    gap: 4px;
  }}
  .cover-count-row {{
    display: grid;
    grid-template-columns: 1fr auto;
    gap: 8px;
    align-items: center;
    font-family: 'DM Mono', monospace;
    font-size: 8px;
    color: #ffffff;
    padding: 3px 0;
    border-bottom: 1px solid #1a233c;
  }}
  .cover-count-row:last-child {{ border-bottom: 0; }}
  .cover-count-label {{
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    opacity: 0.9;
  }}
  .cover-count-value {{
    color: #f5c518;
    font-weight: 700;
    opacity: 1;
  }}
  .cover-panel {{
    border: 1px solid #263050;
    background: #0f1526;
    border-radius: 6px;
    padding: 7px 8px;
  }}
  .cover-panel-head {{
    font-family: 'DM Mono', monospace;
    font-size: 8px;
    color: #ffffff;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 5px;
    opacity: 0.82;
  }}
  .cover-panel-grid-head {{
    display: grid;
    grid-template-columns: 1fr 48px 56px;
    gap: 6px;
    align-items: center;
    margin-bottom: 5px;
  }}
  .cover-panel-grid-head span:nth-child(2),
  .cover-panel-grid-head span:nth-child(3) {{
    text-align: right;
  }}
  .cover-panel-grid-head span:nth-child(3) {{
    color: #f5c518;
    opacity: 0.95;
  }}
  .cover-chip-list {{
    display: flex;
    flex-direction: column;
    gap: 4px;
  }}
  .cover-chip {{
    display: grid;
    grid-template-columns: minmax(0, 1fr) 48px 56px;
    align-items: center;
    gap: 6px;
    background: #0b101d;
    border: 1px solid #1b243d;
    border-radius: 6px;
    padding: 4px 6px;
  }}
  .cover-chip-text {{
    min-width: 0;
  }}
  .cover-chip-name {{
    font-size: 10px;
    font-weight: 700;
    color: #ffffff;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .cover-chip-meta {{
    font-family: 'DM Mono', monospace;
    font-size: 7px;
    color: #ffffff;
    opacity: 0.72;
    margin-top: 1px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .cover-chip-empty {{
    font-size: 9px;
    color: #cfd5ee;
    opacity: 0.7;
    padding: 6px 4px;
  }}
  .cover-chip-hit,
  .cover-chip-odds {{
    font-family: 'DM Mono', monospace;
    font-size: 9px;
    color: #ffffff;
    text-align: right;
    white-space: nowrap;
  }}
  .cover-chip-odds {{
    color: #f5c518;
    font-weight: 700;
  }}
  .cover-disclaimer {{
    font-family: 'DM Mono', monospace;
    font-size: 8px;
    color: #ffffff;
    opacity: 0.65;
    line-height: 1.3;
  }}
  .card-footer {{
    padding: 7px 18px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #070a13;
    border-top: 1px solid #13162a;
    flex-shrink: 0;
    position: relative;
    z-index: 1;
  }}
  .footer-left {{
    font-size: 8px;
    font-weight: 600;
    letter-spacing: 0.06em;
    color: #ffffff;
    opacity: 0.45;
    text-transform: uppercase;
  }}
  .footer-right {{
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.08em;
    color: #F5C518;
    opacity: 0.7;
    text-transform: uppercase;
  }}
</style>
</head>
<body>
<div class="canvas">
  <div class="scale">
    <div class="card" id="card">
      <div class="corner tr"></div>
      <div class="corner bl"></div>
      {card_markup}
    </div>
  </div>
</div>
<script>
  const waitFonts = Promise.resolve(document.fonts && document.fonts.ready ? document.fonts.ready : null)
    .catch(() => null);
  const waitImages = Promise.all(
    Array.from(document.images || []).map((img) => {{
      if (img.complete) return Promise.resolve();
      return new Promise((resolve) => {{
        img.addEventListener('load', resolve, {{ once: true }});
        img.addEventListener('error', resolve, {{ once: true }});
      }});
    }})
  ).catch(() => null);
  Promise.all([waitFonts, waitImages]).finally(() => document.body.classList.add('ready'));
</script>
</body>
</html>
"""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_render_bundle_manifest(
    *,
    manifest: dict[str, Any],
    html_slides: list[Path],
    image_slides: list[Path],
    output_dir: Path,
) -> Path:
    payload = {
        "version": 1,
        "source_manifest": {
            "post_type": manifest.get("post_type"),
            "scheduled_for": manifest.get("scheduled_for"),
            "content_fingerprint": manifest.get("content_fingerprint"),
        },
        "output_dir": str(output_dir),
        "html_slides": [
            {"path": str(p), "sha256": _sha256_file(p), "bytes": p.stat().st_size}
            for p in html_slides
        ],
        "image_slides": [
            {"path": str(p), "sha256": _sha256_file(p), "bytes": p.stat().st_size}
            for p in image_slides
            if p.exists()
        ],
    }
    path = output_dir / "render_manifest.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def write_slide_html_files(manifest: dict[str, Any], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    html_paths: list[Path] = []
    for slide in list(manifest.get("slides") or []):
        slide_no = int(slide.get("slide_number") or (len(html_paths) + 1))
        path = output_dir / f"slide_{slide_no:02d}.html"
        path.write_text(_slide_html_document(manifest, slide), encoding="utf-8")
        html_paths.append(path)
    return html_paths


def _run_playwright_screenshot(
    html_path: Path,
    image_path: Path,
    *,
    playwright_pkg: str,
    browser_channel: str | None,
    timeout_ms: int,
) -> None:
    image_path.parent.mkdir(parents=True, exist_ok=True)
    file_url = html_path.resolve().as_uri()
    cmd = [
        "npx",
        "-y",
        playwright_pkg,
        "screenshot",
        "--viewport-size",
        f"{CARD_WIDTH},{CARD_HEIGHT}",
        "--wait-for-selector",
        "body.ready",
        "--timeout",
        str(timeout_ms),
    ]
    if browser_channel:
        cmd.extend(["--browser", "chromium", "--channel", browser_channel])
    else:
        cmd.extend(["--browser", "chromium"])
    cmd.extend([file_url, str(image_path)])
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        stdout = (result.stdout or "").strip()
        msg = (
            f"Playwright screenshot failed for {html_path.name}\n"
            f"Command: {' '.join(shlex.quote(part) for part in cmd)}\n"
        )
        if stdout:
            msg += f"stdout:\n{stdout}\n"
        if stderr:
            msg += f"stderr:\n{stderr}\n"
        msg += (
            "If this is the first run, install Chromium for Playwright first:\n"
            f"  npx -y {playwright_pkg} install chromium"
        )
        if not browser_channel:
            msg += (
                "\nOr use a locally installed Chrome without downloading Playwright browsers:\n"
                "  --playwright-channel chrome"
            )
        raise RuntimeError(msg)


def render_carousel_images(
    manifest: dict[str, Any],
    output_dir: Path,
    *,
    manifest_path: Path | None = None,
    image_ext: str = "png",
    playwright_pkg: str = PLAYWRIGHT_PKG_DEFAULT,
    browser_channel: str | None = None,
    timeout_ms: int = 60000,
) -> RenderedCarousel:
    """Render manifest to per-slide HTML + raster images using Playwright CLI."""
    html_dir = output_dir / "html"
    image_dir = output_dir / "images"
    html_paths = write_slide_html_files(manifest, html_dir)

    rendered: list[RenderedSlide] = []
    image_paths: list[Path] = []
    normalized_ext = image_ext.lower().lstrip(".")
    if normalized_ext not in {"png", "jpg", "jpeg"}:
        raise ValueError("image_ext must be png/jpg/jpeg")

    for slide_no, html_path in enumerate(html_paths, start=1):
        image_path = image_dir / f"slide_{slide_no:02d}.{normalized_ext}"
        _run_playwright_screenshot(
            html_path,
            image_path,
            playwright_pkg=playwright_pkg,
            browser_channel=browser_channel,
            timeout_ms=timeout_ms,
        )
        image_paths.append(image_path)
        rendered.append(
            RenderedSlide(
                slide_number=slide_no,
                path=image_path,
                width=CARD_WIDTH,
                height=CARD_HEIGHT,
            )
        )

    _write_render_bundle_manifest(
        manifest=manifest,
        html_slides=html_paths,
        image_slides=image_paths,
        output_dir=output_dir,
    )
    return RenderedCarousel(manifest_path=manifest_path, slides=rendered)


def render_debug_html_preview(manifest: dict[str, Any], output_path: Path) -> Path:
    """Write a compact HTML preview grid for quick visual QA of a manifest."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    slides = list(manifest.get("slides") or [])
    slide_cards: list[str] = []
    for slide in slides:
        slide_no = int(slide.get("slide_number") or 0)
        slide_cards.append(
            f"""
            <div class="tile">
              <div class="label">Slide {slide_no}/{int(slide.get('slide_count') or len(slides))} · {_html_escape(slide.get('slide_type'))}</div>
              <iframe src="{_html_escape(f"slides_html/slide_{slide_no:02d}.html")}"></iframe>
            </div>
            """
        )
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Instagram Carousel QA Preview</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; padding: 24px; background: #05070d; color: #e2e2e2; font-family: system-ui, sans-serif; }}
    .meta {{ margin-bottom: 18px; color: #a0a7c2; }}
    .grid {{ display: grid; gap: 16px; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); }}
    .tile {{ background: #0d0f1a; border: 1px solid #1a1f33; border-radius: 8px; padding: 10px; }}
    .label {{ font-size: 12px; color: #f5c518; margin-bottom: 8px; }}
    iframe {{ width: 270px; height: 338px; border: 0; display: block; margin: 0 auto; background: #030508; }}
    pre {{ white-space: pre-wrap; word-break: break-word; background: #0a0c14; padding: 12px; border-radius: 8px; }}
  </style>
</head>
<body>
  <div class="meta">
    <div><strong>{_html_escape(manifest.get("title"))}</strong></div>
    <div>{_html_escape(manifest.get("scheduled_for"))} · rows={int(((manifest.get("counts") or {}).get("total_rows") or 0))} · slides={len(slides)}</div>
  </div>
  <div class="grid">{''.join(slide_cards)}</div>
  <h3>Caption</h3>
  <pre>{_html_escape(manifest.get("caption") or "")}</pre>
</body>
</html>
"""
    output_path.write_text(html, encoding="utf-8")
    return output_path


def write_debug_preview_bundle(manifest: dict[str, Any], output_dir: Path) -> Path:
    """Write per-slide HTML files plus an iframe-based QA index page."""
    slides_dir = output_dir / "slides_html"
    write_slide_html_files(manifest, slides_dir)
    return render_debug_html_preview(manifest, output_dir / "index.html")
