from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests
from dotenv import load_dotenv


load_dotenv()
load_dotenv(".env.local", override=False)

DEFAULT_GAMMA_BASE_URL = "https://gamma-api.polymarket.com"


@dataclass(frozen=True)
class TrackedMarket:
    slug: str
    label: str
    top_n: int = 6


TRACKED_MARKETS: tuple[TrackedMarket, ...] = (
    TrackedMarket("english-premier-league-winner", "EPL Winner"),
    TrackedMarket("uefa-champions-league-winner", "UCL Winner"),
    TrackedMarket("la-liga-winner-114", "La Liga Winner"),
    TrackedMarket("2025-2026-pfa-players-player-of-the-year-winner", "PFA Player Of The Year"),
    TrackedMarket("ballon-dor-winner-2026", "Ballon d'Or Winner"),
    TrackedMarket("english-premier-league-top-4-finish", "EPL Top 4"),
    TrackedMarket("epl-which-clubs-get-relegated", "EPL Relegation"),
    TrackedMarket("next-manchester-united-manager", "Next Man Utd Manager"),
    TrackedMarket("will-theunitedstrand-get-a-haircut-by-2025-26-season-end", "TheUnitedStrand Haircut"),
)

LABEL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^Will (.+?) win\b", re.IGNORECASE), "{name}"),
    (re.compile(r"^Will (.+?) finish in the top 4\b", re.IGNORECASE), "{name} (Top 4)"),
    (re.compile(r"^Will (.+?) be relegated\b", re.IGNORECASE), "{name} (Relegated)"),
    (re.compile(r"^Will (.+?) be appointed as manager\b", re.IGNORECASE), "{name}"),
    (re.compile(r"^Will (.+?) get a haircut\b", re.IGNORECASE), "{name}"),
)


def _parse_json_array(value: object) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _normalize_label(question: str, fallback: str) -> str:
    clean = question.strip().rstrip("?")
    for pattern, template in LABEL_PATTERNS:
        matched = pattern.match(clean)
        if matched:
            return template.format(name=matched.group(1))
    return fallback


def _midpoint_price(market: dict, fallback: float) -> float:
    """Return bid/ask midpoint, falling back to last trade or outcomePrices."""
    try:
        bid = float(market.get("bestBid", 0))
        ask = float(market.get("bestAsk", 0))
    except (TypeError, ValueError):
        bid, ask = 0.0, 0.0
    if bid > 0 and ask > 0:
        return (bid + ask) / 2
    try:
        last = float(market.get("lastTradePrice", 0))
    except (TypeError, ValueError):
        last = 0.0
    return last if last > 0 else fallback


def _get_yes_probability(
    outcomes: list[str],
    prices: list[float],
) -> float | None:
    for outcome, price in zip(outcomes, prices):
        if outcome.lower() == "yes":
            return price
    return None


def _extract_outcomes(event: dict, top_n: int) -> list[dict]:
    rows: list[dict] = []
    for market in event.get("markets") or []:
        outcomes = _parse_json_array(market.get("outcomes"))
        prices = _parse_json_array(market.get("outcomePrices"))
        if not outcomes or not prices:
            continue

        normalized_outcomes = [str(value) for value in outcomes]
        normalized_prices: list[float] = []
        for value in prices:
            try:
                normalized_prices.append(float(value))
            except (TypeError, ValueError):
                normalized_prices.append(0.0)

        size = min(len(normalized_outcomes), len(normalized_prices))
        if size == 0:
            continue
        normalized_outcomes = normalized_outcomes[:size]
        normalized_prices = normalized_prices[:size]

        question = str(market.get("question") or "").strip()
        lower_outcomes = {outcome.lower() for outcome in normalized_outcomes}
        best_bid = market.get("bestBid")
        best_ask = market.get("bestAsk")
        last_trade = market.get("lastTradePrice")

        if lower_outcomes == {"yes", "no"}:
            fallback_price = _get_yes_probability(normalized_outcomes, normalized_prices)
            if fallback_price is None:
                continue
            probability = _midpoint_price(market, fallback_price)
            rows.append(
                {
                    "label": _normalize_label(question, question or "Yes"),
                    "probability": probability,
                    "question": question,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "last_trade_price": last_trade,
                    "outcome": "Yes",
                }
            )
            continue

        for outcome, price in zip(normalized_outcomes, normalized_prices):
            rows.append(
                {
                    "label": outcome,
                    "probability": _midpoint_price(market, price),
                    "question": question,
                    "best_bid": best_bid,
                    "best_ask": best_ask,
                    "last_trade_price": last_trade,
                    "outcome": outcome,
                }
            )

    rows.sort(key=lambda item: item["probability"], reverse=True)
    return rows[:top_n]


def _load_previous_probabilities(snapshot_path: Path) -> dict[tuple[str, str], float]:
    if not snapshot_path.exists():
        return {}
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}

    probabilities: dict[tuple[str, str], float] = {}
    for market in payload.get("tracked_markets", []):
        slug = market.get("slug")
        if not slug:
            continue
        for outcome in market.get("top_outcomes", []):
            label = outcome.get("label")
            probability = outcome.get("probability")
            if label is None or probability is None:
                continue
            probabilities[(slug, label)] = float(probability)
    return probabilities


def _fetch_event(base_url: str, slug: str, timeout_sec: int) -> dict:
    response = requests.get(
        f"{base_url.rstrip('/')}/events",
        params={"slug": slug},
        timeout=timeout_sec,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, list) or not payload:
        raise RuntimeError(f"No event found for slug: {slug}")
    return payload[0]


def _format_delta(delta: float | None) -> str:
    if delta is None:
        return "new"
    if abs(delta) < 1e-9:
        return "0.0pp"
    sign = "+" if delta > 0 else ""
    return f"{sign}{delta:.1f}pp"


def _format_percent(probability: float | None) -> str:
    if probability is None:
        return "n/a"
    pct = probability * 100
    rounded = round(pct)
    if abs(pct - rounded) < 0.05:
        return f"{int(rounded)}%"
    return f"{pct:.1f}%"


def _to_posts(
    snapshot: dict,
    window_label: str,
    min_change_pp: float,
    post_top_n: int,
) -> str:
    sections: list[str] = []
    for market in snapshot.get("tracked_markets", []):
        top_outcomes = list(market.get("top_outcomes", []))[:post_top_n]
        if not top_outcomes:
            continue

        has_meaningful_change = any(
            outcome.get("delta_pp") is not None and abs(float(outcome["delta_pp"])) >= min_change_pp
            for outcome in top_outcomes
        )
        if not has_meaningful_change:
            continue

        lines: list[str] = []
        lines.append(f"🏆 Change in {market['label']} probability {window_label}:")
        lines.append("")
        for outcome in top_outcomes:
            label = outcome.get("label", "Unknown")
            previous = outcome.get("previous_probability")
            current = outcome.get("probability")
            lines.append(f"• {label}: {_format_percent(previous)} -> {_format_percent(current)}")
        lines.append("")
        lines.append("[🔮 via @Polymarket]")
        lines.append(market.get("url", ""))
        sections.append("\n".join(lines))

    if sections:
        return "\n\n".join(sections).rstrip() + "\n"

    generated_at = snapshot.get("generated_at")
    return (
        "No tracked market changes met the posting threshold.\n\n"
        f"- Threshold: {min_change_pp:.1f}pp\n"
        f"- Window: {window_label}\n"
        f"- Generated: {generated_at}\n"
    )


def _to_markdown(snapshot: dict) -> str:
    lines: list[str] = []
    lines.append("# Polymarket Tracking Snapshot")
    lines.append("")
    lines.append(f"- Generated: `{snapshot['generated_at']}`")
    lines.append(f"- Source: `{snapshot['source']['base_url']}`")
    lines.append("")

    if snapshot.get("errors"):
        lines.append("## Errors")
        lines.append("")
        for error in snapshot["errors"]:
            lines.append(f"- `{error['slug']}`: {error['error']}")
        lines.append("")

    lines.append("## Markets")
    lines.append("")
    for market in snapshot["tracked_markets"]:
        lines.append(f"### {market['label']}")
        lines.append(f"- Slug: `{market['slug']}`")
        lines.append(f"- URL: {market['url']}")
        lines.append(
            f"- Status: `active={market['active']}` `closed={market['closed']}` "
            f"`end={market['end_date']}` `volume={market['volume']}`"
        )
        lines.append("")
        lines.append("| Outcome | Probability | Move |")
        lines.append("|---|---:|---:|")
        for outcome in market["top_outcomes"]:
            lines.append(
                f"| {outcome['label']} | {outcome['probability'] * 100:.1f}% | "
                f"{_format_delta(outcome.get('delta_pp'))} |"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def run(
    markets: Iterable[TrackedMarket],
    base_url: str,
    out_dir: Path,
    timeout_sec: int,
    strict: bool,
    window_label: str,
    min_change_pp: float,
    post_top_n: int,
) -> int:
    snapshots_dir = out_dir / "snapshots"
    tracker_dir = out_dir / "tracker"
    snapshots_dir.mkdir(parents=True, exist_ok=True)
    tracker_dir.mkdir(parents=True, exist_ok=True)

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    latest_path = snapshots_dir / "latest.json"
    dated_snapshot_path = snapshots_dir / f"{today}_snapshot.json"
    dated_previous_path = snapshots_dir / f"{today}_previous.json"
    markdown_path = tracker_dir / f"{today}_tracker.md"
    posts_path = tracker_dir / f"{today}_midweek_posts.txt"

    if latest_path.exists():
        shutil.copyfile(latest_path, dated_previous_path)
    previous_probabilities = _load_previous_probabilities(dated_previous_path)

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    tracked_payload: list[dict] = []
    errors: list[dict] = []

    for tracked in markets:
        try:
            event = _fetch_event(base_url=base_url, slug=tracked.slug, timeout_sec=timeout_sec)
            outcomes = _extract_outcomes(event, top_n=tracked.top_n)
            for outcome in outcomes:
                previous = previous_probabilities.get((tracked.slug, outcome["label"]))
                outcome["previous_probability"] = previous
                outcome["delta_pp"] = None if previous is None else (outcome["probability"] - previous) * 100

            tracked_payload.append(
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
        except Exception as exc:  # pragma: no cover - defensive logging
            errors.append({"slug": tracked.slug, "error": str(exc)})

    snapshot = {
        "generated_at": generated_at,
        "source": {"base_url": base_url},
        "tracked_markets": tracked_payload,
        "errors": errors,
    }

    latest_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    dated_snapshot_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    markdown_path.write_text(_to_markdown(snapshot), encoding="utf-8")
    posts_path.write_text(
        _to_posts(
            snapshot=snapshot,
            window_label=window_label,
            min_change_pp=max(min_change_pp, 0.0),
            post_top_n=max(post_top_n, 1),
        ),
        encoding="utf-8",
    )

    if strict and errors:
        return 1
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Track selected Polymarket markets and snapshot probabilities.")
    parser.add_argument(
        "--base-url",
        default=os.getenv("POLYMARKET_GAMMA_BASE_URL", DEFAULT_GAMMA_BASE_URL),
        help="Polymarket Gamma API base URL.",
    )
    parser.add_argument(
        "--out-dir",
        default="output/polymarket",
        help="Output directory for tracker artifacts.",
    )
    parser.add_argument(
        "--timeout-sec",
        type=int,
        default=20,
        help="HTTP request timeout in seconds.",
    )
    parser.add_argument(
        "--strict",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exit non-zero when one or more tracked markets fail to load.",
    )
    parser.add_argument(
        "--window-label",
        default="since last update",
        help="Text label used in post copy (e.g. 'after this weekend').",
    )
    parser.add_argument(
        "--min-change-pp",
        type=float,
        default=0.5,
        help="Minimum absolute percentage-point move required to include a market in post output.",
    )
    parser.add_argument(
        "--post-top-n",
        type=int,
        default=3,
        help="How many top outcomes to include per post snippet.",
    )
    args = parser.parse_args()

    exit_code = run(
        markets=TRACKED_MARKETS,
        base_url=args.base_url,
        out_dir=Path(args.out_dir),
        timeout_sec=max(args.timeout_sec, 1),
        strict=args.strict,
        window_label=args.window_label,
        min_change_pp=args.min_change_pp,
        post_top_n=args.post_top_n,
    )
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
