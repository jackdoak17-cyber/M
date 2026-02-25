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
    thresholds = manifest.get("thresholds") or {}
    min_hit_pct = float(thresholds.get("min_hit_pct") or 0)
    min_odds = float(thresholds.get("min_odds") or 0)
    min_starts = int(thresholds.get("min_starts") or 0)
    return f"{int(round(min_hit_pct * 100))}%+ HIT RATE · ODDS >{min_odds:.2f} · MIN N={min_starts}"


def _title_words_for_manifest(manifest: dict[str, Any]) -> tuple[str, str]:
    if manifest.get("post_type") == "potential_value":
        return ("POTENTIAL", "VALUE")
    return ("HIGH", "PROBABILITY")


def _post_badge_for_manifest(manifest: dict[str, Any]) -> str:
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
      <div class="footer-left">All odds Bet365 · Starter-only hit rate</div>
      <div class="footer-right">@Odds_Analyst</div>
    </div>
    """


def _render_cover_body(manifest: dict[str, Any], slide: dict[str, Any]) -> str:
    stats = slide.get("stats") or {}
    title_words = slide.get("title_words") or {}
    primary = str(title_words.get("primary") or _title_words_for_manifest(manifest)[0])
    accent = str(title_words.get("accent") or _title_words_for_manifest(manifest)[1])
    icon = "📈" if manifest.get("post_type") == "potential_value" else "📊"
    fixture_window = str(slide.get("fixture_window") or "")
    fixture_meta = (
        f'<div class="cover-fixture-window">{_html_escape(fixture_window)}</div>' if fixture_window else ""
    )
    return f"""
    <div class="cover-body">
      <div class="cover-icon">{icon}</div>
      <div class="main-title cover-title">{_html_escape(primary)} <span>{_html_escape(accent)}</span></div>
      <div class="cover-desc">{_html_escape(manifest.get("intro") or "")}</div>
      {fixture_meta}
      <div class="cover-stats">
        <div class="cover-stat">
          <div class="cover-stat-num">{int(stats.get("total_players") or 0)}</div>
          <div class="cover-stat-label">Players</div>
        </div>
        <div class="cover-stat">
          <div class="cover-stat-num">{int(stats.get("stat_types") or 0)}</div>
          <div class="cover-stat-label">Stat Types</div>
        </div>
        <div class="cover-stat">
          <div class="cover-stat-num">{int(stats.get("hit_rate_threshold_pct") or 0)}%+</div>
          <div class="cover-stat-label">Hit Rate</div>
        </div>
      </div>
      <div class="swipe-hint">
        <div class="swipe-text">Swipe to explore</div>
        <div class="swipe-arrow">→</div>
      </div>
    </div>
    """


def _render_section_rows(slide: dict[str, Any]) -> str:
    rows = list(slide.get("rows") or [])
    rendered: list[str] = []
    for idx, row in enumerate(rows):
        alt = " alt" if idx % 2 == 1 else ""
        display = row.get("display") or {}
        rendered.append(
            f"""
    <div class="player-row{alt}">
      <span class="arrow">→</span>
      <div class="player-info">
        <div class="player-name">{_html_escape(row.get("player_name"))}</div>
        <div class="player-club">{_html_escape(row.get("team_name"))}</div>
      </div>
      <div class="player-right">
        <div class="hit-rate">won in <strong>{_html_escape(display.get("rate"))}</strong></div>
        <div class="odds-pill">{_html_escape(display.get("odds"))}</div>
      </div>
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
        <span class="section-label">{_html_escape(section_label + page_suffix)}</span>
        <div class="section-divider"></div>
        <span class="section-meta">Hit Rate · Odds</span>
      </div>
      <div class="player-list">{_render_section_rows(slide)}</div>
    </div>
    """


def _build_slide_markup(manifest: dict[str, Any], slide: dict[str, Any]) -> str:
    body_markup = (
        _render_cover_body(manifest, slide)
        if slide.get("slide_type") == "cover"
        else _render_section_body(slide)
    )
    return _render_header(manifest, slide) + body_markup + _render_footer()


def _slide_html_document(manifest: dict[str, Any], slide: dict[str, Any]) -> str:
    title = f"{manifest.get('post_type')} slide {slide.get('slide_number')}"
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
    position: absolute;
    width: 110px;
    height: 110px;
    background: repeating-linear-gradient(
      -45deg,
      #F5C518 0px, #F5C518 5px,
      transparent 5px, transparent 13px
    );
    opacity: 0.15;
    pointer-events: none;
    z-index: 0;
  }}
  .corner.tr {{ top: -18px; right: -18px; }}
  .corner.bl {{ bottom: -18px; left: -18px; }}
  .card-header {{
    padding: 18px 26px 14px;
    border-bottom: 2px solid #F5C518;
    position: relative;
    z-index: 1;
    flex-shrink: 0;
  }}
  .header-top {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 10px;
  }}
  .brand {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 12px;
    letter-spacing: 0.14em;
    color: #3a3d52;
  }}
  .brand span {{ color: #F5C518; opacity: 0.7; }}
  .header-right {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .post-badge {{
    font-size: 9px;
    font-weight: 700;
    letter-spacing: 0.14em;
    color: #0d0f1a;
    background: #F5C518;
    padding: 2px 8px;
    border-radius: 2px;
    text-transform: uppercase;
  }}
  .date-badge {{
    font-family: 'DM Mono', monospace;
    font-size: 9px;
    color: #3a3d52;
  }}
  .main-title {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 42px;
    letter-spacing: 0.05em;
    color: #fff;
    line-height: 0.92;
    margin-bottom: 8px;
  }}
  .main-title span {{ color: #F5C518; }}
  .threshold-bar {{
    display: flex;
    align-items: center;
    gap: 8px;
  }}
  .tline {{ flex: 1; height: 1px; background: #F5C518; opacity: 0.25; }}
  .ttext {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 13px;
    letter-spacing: 0.1em;
    color: #F5C518;
    opacity: 0.75;
    white-space: nowrap;
  }}
  .slide-indicator {{
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 4px;
    margin-top: 8px;
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
    background: #13162a;
    border-bottom: 1px solid #1e2138;
    padding: 8px 26px;
    gap: 10px;
    flex-shrink: 0;
  }}
  .section-label {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 17px;
    letter-spacing: 0.08em;
    color: #F5C518;
  }}
  .section-divider {{ flex: 1; height: 1px; background: #252840; }}
  .section-meta {{
    font-family: 'DM Mono', monospace;
    font-size: 9px;
    color: #353850;
    letter-spacing: 0.08em;
    text-transform: uppercase;
  }}
  .player-list {{ flex: 1; overflow: hidden; }}
  .player-row {{
    display: flex;
    align-items: center;
    padding: 0 26px;
    height: 46px;
    border-bottom: 1px solid #10121e;
  }}
  .player-row.alt {{ background: #0f1120; }}
  .arrow {{
    color: #F5C518;
    font-size: 10px;
    font-family: 'DM Mono', monospace;
    margin-right: 10px;
    opacity: 0.6;
    flex-shrink: 0;
  }}
  .player-info {{ flex: 1; min-width: 0; }}
  .player-name {{
    font-size: 15px;
    font-weight: 700;
    color: #e2e2e2;
    letter-spacing: 0.02em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    line-height: 1;
  }}
  .player-club {{
    font-size: 10px;
    font-weight: 500;
    color: #404460;
    letter-spacing: 0.04em;
    text-transform: uppercase;
    margin-top: 2px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .player-right {{
    display: flex;
    align-items: center;
    gap: 8px;
    flex-shrink: 0;
    margin-left: 8px;
  }}
  .hit-rate {{
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    color: #484c66;
    white-space: nowrap;
  }}
  .hit-rate strong {{ color: #888; font-weight: 500; }}
  .odds-pill {{
    font-family: 'DM Mono', monospace;
    font-size: 12px;
    font-weight: 500;
    color: #0d0f1a;
    background: #F5C518;
    padding: 4px 10px;
    border-radius: 3px;
    min-width: 52px;
    text-align: center;
  }}
  .cover-body {{
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    padding: 28px;
    gap: 16px;
    position: relative;
    z-index: 1;
    text-align: center;
  }}
  .cover-title {{ margin-bottom: 0; }}
  .cover-icon {{
    font-size: 40px;
    margin-bottom: 4px;
  }}
  .cover-desc {{
    font-size: 14px;
    font-weight: 500;
    color: #555;
    text-align: center;
    letter-spacing: 0.04em;
    line-height: 1.45;
    max-width: 420px;
  }}
  .cover-fixture-window {{
    font-family: 'DM Mono', monospace;
    font-size: 10px;
    color: #67708e;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    border: 1px solid #1e2138;
    background: #111424;
    padding: 6px 12px;
    border-radius: 4px;
  }}
  .cover-stats {{
    display: flex;
    gap: 16px;
    margin-top: 4px;
  }}
  .cover-stat {{
    background: #13162a;
    border: 1px solid #1e2138;
    border-radius: 6px;
    padding: 10px 18px;
    text-align: center;
    min-width: 104px;
  }}
  .cover-stat-num {{
    font-family: 'Bebas Neue', sans-serif;
    font-size: 28px;
    color: #F5C518;
    letter-spacing: 0.04em;
    line-height: 1;
  }}
  .cover-stat-label {{
    font-size: 10px;
    font-weight: 600;
    color: #444;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-top: 2px;
  }}
  .swipe-hint {{
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 8px;
  }}
  .swipe-text {{
    font-size: 10px;
    font-weight: 600;
    color: #333;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    font-family: 'DM Mono', monospace;
  }}
  .swipe-arrow {{
    color: #F5C518;
    font-size: 14px;
    opacity: 0.5;
    animation: nudge 1.5s ease-in-out infinite;
  }}
  @keyframes nudge {{
    0%, 100% {{ transform: translateX(0); opacity: 0.5; }}
    50% {{ transform: translateX(4px); opacity: 1; }}
  }}
  .card-footer {{
    padding: 9px 26px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    background: #080a14;
    border-top: 1px solid #13162a;
    flex-shrink: 0;
    position: relative;
    z-index: 1;
  }}
  .footer-left {{
    font-size: 9px;
    font-weight: 600;
    letter-spacing: 0.1em;
    color: #282b3a;
    text-transform: uppercase;
  }}
  .footer-right {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 0.1em;
    color: #F5C518;
    opacity: 0.45;
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
  Promise.resolve(document.fonts && document.fonts.ready ? document.fonts.ready : null)
    .catch(() => null)
    .finally(() => document.body.classList.add('ready'));
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
    image_ext: str = "jpeg",
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
