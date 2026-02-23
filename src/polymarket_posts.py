from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.polymarket_tracker import DEFAULT_GAMMA_BASE_URL, TRACKED_MARKETS, _extract_outcomes, _fetch_event


POSTS_DIR = Path("output/polymarket/weekly")
DEFAULT_BASELINE_PATH = Path("output/polymarket/weekly_baseline.json")
MOVER_THRESHOLD_PP = 5.0

PL_SECTION_CONFIG = (
    {
        "title": "Title Race",
        "slug": "english-premier-league-winner",
        "count": 4,
    },
    {
        "title": "Top 4 Race",
        "slug": "english-premier-league-top-4-finish",
        "count": 7,
    },
    {
        "title": "Relegation Watch",
        "slug": "epl-which-clubs-get-relegated",
        "count": 7,
    },
)

PL_SECTION_SLUGS = {section["slug"] for section in PL_SECTION_CONFIG}


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _round_pct(probability: float) -> int:
    return int(round(probability * 100))


def _arrow(previous_pct: int, current_pct: int) -> str:
    if current_pct > previous_pct:
        return "↑"
    if current_pct < previous_pct:
        return "↓"
    return "—"


def _clean_label(label: str) -> str:
    return label.removesuffix(" (Top 4)").removesuffix(" (Relegated)").strip()


def _build_probability_map(snapshot: dict[str, Any], slug: str) -> dict[str, float]:
    market = next((item for item in snapshot.get("tracked_markets", []) if item.get("slug") == slug), None)
    if not market:
        return {}
    return {
        str(outcome.get("label")): float(outcome.get("probability"))
        for outcome in market.get("top_outcomes", [])
        if outcome.get("label") is not None and outcome.get("probability") is not None
    }


def _build_snapshot(base_url: str, timeout_sec: int) -> dict[str, Any]:
    tracked_markets: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    for tracked in TRACKED_MARKETS:
        try:
            event = _fetch_event(base_url=base_url, slug=tracked.slug, timeout_sec=timeout_sec)
            # Pull a larger set so the weekly post can pick top-7 safely.
            outcomes = _extract_outcomes(event, top_n=100)
            tracked_markets.append(
                {
                    "slug": tracked.slug,
                    "label": tracked.label,
                    "url": f"https://polymarket.com/event/{tracked.slug}",
                    "active": bool(event.get("active")),
                    "closed": bool(event.get("closed")),
                    "end_date": event.get("endDate"),
                    "volume": event.get("volume"),
                    "top_outcomes": outcomes,
                }
            )
        except Exception as exc:  # pragma: no cover - defensive runtime path
            errors.append({"slug": tracked.slug, "error": str(exc)})
    return {
        "generated_at": _iso_utc_now(),
        "source": {"base_url": base_url},
        "tracked_markets": tracked_markets,
        "errors": errors,
    }


def _market_from_snapshot(snapshot: dict[str, Any] | None, slug: str) -> dict[str, Any] | None:
    if not snapshot:
        return None
    return next((item for item in snapshot.get("tracked_markets", []) if item.get("slug") == slug), None)


def _render_pl_market_watch(current: dict[str, Any], baseline: dict[str, Any] | None) -> str:
    lines: list[str] = ["Premier League Market Watch", ""]
    first_run = baseline is None

    section_blocks: list[str] = []
    for section in PL_SECTION_CONFIG:
        slug = section["slug"]
        market = _market_from_snapshot(current, slug)
        if not market or market.get("closed"):
            continue

        current_rows = list(market.get("top_outcomes", []))[: int(section["count"])]
        if not current_rows:
            continue

        baseline_probs = _build_probability_map(baseline, slug) if baseline else {}
        block_lines: list[str] = [str(section["title"])]
        for row in current_rows:
            label = _clean_label(str(row.get("label") or "Unknown"))
            current_prob = float(row.get("probability") or 0.0)
            current_pct = _round_pct(current_prob)

            if first_run:
                block_lines.append(f"• {label}: {current_pct}%")
                continue

            previous_prob = baseline_probs.get(str(row.get("label")))
            if previous_prob is None:
                block_lines.append(f"• {label}: {current_pct}%")
                continue

            previous_pct = _round_pct(previous_prob)
            block_lines.append(
                f"• {label}: {previous_pct}% → {current_pct}% {_arrow(previous_pct, current_pct)}"
            )
        section_blocks.append("\n".join(block_lines))

    if section_blocks:
        lines.append("\n\n".join(section_blocks))
        lines.append("")
    lines.append("All odds via Polymarket")
    return "\n".join(lines).rstrip() + "\n"


def _market_max_move_pp(
    current_market: dict[str, Any],
    baseline_probs: dict[str, float],
) -> float:
    maximum = 0.0
    for row in current_market.get("top_outcomes", []):
        label = str(row.get("label") or "")
        if not label or label not in baseline_probs:
            continue
        current_prob = float(row.get("probability") or 0.0)
        move = abs((current_prob - baseline_probs[label]) * 100)
        if move > maximum:
            maximum = move
    return maximum


def _render_mover_post(
    market_label: str,
    current_market: dict[str, Any],
    baseline_probs: dict[str, float],
) -> str:
    rows = list(current_market.get("top_outcomes", []))[:5]
    lines: list[str] = ["Polymarket Mover", "", f"{market_label} odds shifted:", ""]
    for row in rows:
        label = _clean_label(str(row.get("label") or "Unknown"))
        current_prob = float(row.get("probability") or 0.0)
        previous_prob = float(baseline_probs.get(str(row.get("label")), current_prob))
        previous_pct = _round_pct(previous_prob)
        current_pct = _round_pct(current_prob)
        lines.append(f"• {label}: {previous_pct}% → {current_pct}% {_arrow(previous_pct, current_pct)}")
    lines.append("")
    lines.append("via Polymarket")
    return "\n".join(lines).rstrip() + "\n"


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _clear_existing_mover_files(posts_dir: Path) -> None:
    if not posts_dir.exists():
        return
    for path in posts_dir.glob("*biggest_mover_*.txt"):
        path.unlink()


def run(
    generate: bool,
    baseline_path: Path,
    timeout_sec: int,
    base_url: str,
) -> int:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    errors: list[dict[str, str]] = []
    baseline = _load_json(baseline_path)
    if baseline_path.exists() and baseline is None:
        errors.append({"slug": "weekly_baseline", "error": f"Invalid JSON in {baseline_path}"})

    current = _build_snapshot(base_url=base_url, timeout_sec=timeout_sec)
    errors.extend(current.get("errors", []))

    pl_post = _render_pl_market_watch(current=current, baseline=baseline)

    _clear_existing_mover_files(POSTS_DIR)
    _write_file(POSTS_DIR / f"{today}_market_watch.txt", pl_post)

    mover_candidates: list[dict[str, Any]] = []
    if baseline:
        for market in current.get("tracked_markets", []):
            slug = str(market.get("slug") or "")
            if slug in PL_SECTION_SLUGS or market.get("closed"):
                continue

            baseline_probs = _build_probability_map(baseline, slug)
            if not baseline_probs:
                continue

            max_move = _market_max_move_pp(market, baseline_probs)
            if max_move < MOVER_THRESHOLD_PP:
                continue

            mover_candidates.append(
                {
                    "slug": slug,
                    "label": str(market.get("label") or slug),
                    "max_move_pp": max_move,
                    "content": _render_mover_post(
                        market_label=str(market.get("label") or slug),
                        current_market=market,
                        baseline_probs=baseline_probs,
                    ),
                }
            )

    mover_candidates.sort(key=lambda item: item["max_move_pp"], reverse=True)
    for index, mover in enumerate(mover_candidates, start=1):
        _write_file(POSTS_DIR / f"{today}_biggest_mover_{index}.txt", mover["content"])

    summary = {
        "generated_at": current.get("generated_at"),
        "baseline_date": baseline.get("generated_at") if baseline else None,
        "current_date": current.get("generated_at"),
        "mode": "generate" if generate else "preview",
        "baseline_path": str(baseline_path),
        "markets_with_movement": [
            {
                "slug": mover["slug"],
                "label": mover["label"],
                "max_move_pp": round(float(mover["max_move_pp"]), 3),
            }
            for mover in mover_candidates
        ],
        "biggest_mover_triggered": bool(mover_candidates),
        "errors": errors,
    }
    _write_file(POSTS_DIR / f"{today}_summary.json", json.dumps(summary, indent=2))

    if generate:
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(current, indent=2), encoding="utf-8")

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate weekly Polymarket post copy.")
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument("--generate", action="store_true", help="Generate posts and update weekly baseline.")
    mode_group.add_argument("--preview", action="store_true", help="Preview posts without updating weekly baseline.")
    parser.add_argument(
        "--baseline",
        default=str(DEFAULT_BASELINE_PATH),
        help="Path to weekly baseline JSON snapshot.",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=20,
        help="HTTP timeout per market request.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("POLYMARKET_GAMMA_BASE_URL", DEFAULT_GAMMA_BASE_URL),
        help="Polymarket Gamma API base URL.",
    )
    args = parser.parse_args()

    exit_code = run(
        generate=bool(args.generate),
        baseline_path=Path(args.baseline),
        timeout_sec=max(int(args.timeout_sec), 1),
        base_url=str(args.base_url),
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
