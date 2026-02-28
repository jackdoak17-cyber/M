from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FIXTURE_HEADER_RE = re.compile(r"^(?P<header>.+ vs .+ - .+)$")
LINE_RE = re.compile(r"^(?P<label>.+?)\s+\(won in (?P<record>\d+/\d+)\)$")


@dataclass(frozen=True)
class FixtureSheetRow:
    label: str
    record: str


@dataclass(frozen=True)
class FixtureSheetSlide:
    header: str
    rows: list[FixtureSheetRow]


def _canonical_hash(value: Any) -> str:
    return __import__("hashlib").sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def parse_by_fixture_text(content: str) -> tuple[str, list[str], list[FixtureSheetSlide], list[str]]:
    lines = [line.rstrip() for line in content.splitlines()]
    header = ""
    intro: list[str] = []
    outro: list[str] = []
    slides: list[FixtureSheetSlide] = []

    current_header: str | None = None
    current_rows: list[FixtureSheetRow] = []
    seen_fixture = False

    for raw in lines:
        line = raw.strip()
        if not line:
            continue

        match = FIXTURE_HEADER_RE.match(line)
        if match:
            seen_fixture = True
            if current_header:
                slides.append(FixtureSheetSlide(header=current_header, rows=current_rows))
            current_header = match.group("header")
            current_rows = []
            continue

        if not seen_fixture:
            if not header:
                header = line
            else:
                intro.append(line)
            continue

        row_match = LINE_RE.match(line)
        if row_match and current_header:
            current_rows.append(
                FixtureSheetRow(
                    label=row_match.group("label").strip(),
                    record=row_match.group("record"),
                )
            )
            continue

        if current_header:
            slides.append(FixtureSheetSlide(header=current_header, rows=current_rows))
            current_header = None
            current_rows = []
        outro.append(line)

    if current_header:
        slides.append(FixtureSheetSlide(header=current_header, rows=current_rows))

    return header, intro, slides, outro


def verify_by_fixture_manifest(manifest: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    slides = list(manifest.get("slides") or [])
    if not slides:
        return ["manifest has no slides"]
    expected_fixtures = list(((manifest.get("fixtures") or {}).get("items") or []))
    if len(slides) != len(expected_fixtures):
        issues.append(
            f"slide count mismatch (expected {len(expected_fixtures)}, got {len(slides)})"
        )

    for idx, slide in enumerate(slides):
        if slide.get("slide_type") != "fixture_sheet":
            issues.append(f"slide {idx+1} has unexpected type {slide.get('slide_type')}")
        rows = list(slide.get("rows") or [])
        if not rows:
            issues.append(f"slide {idx+1} has no rows")
        for row in rows:
            if not row.get("label"):
                issues.append(f"slide {idx+1} row missing label")
            if not row.get("record"):
                issues.append(f"slide {idx+1} row missing record")

    return issues


def build_by_fixture_manifest(
    *,
    content_path: Path,
    scheduled_for: str,
    content: str,
    slot: str,
    label: str,
) -> dict[str, Any]:
    title, intro_lines, slides_raw, outro_lines = parse_by_fixture_text(content)
    slides: list[dict[str, Any]] = []
    fixture_items: list[dict[str, Any]] = []
    subtitle = "All data driven based on recent form"

    for idx, fixture in enumerate(slides_raw, start=1):
        row_payload = [
            {
                "id": f"{idx}:{row_idx}",
                "label": row.label,
                "record": row.record,
            }
            for row_idx, row in enumerate(fixture.rows, start=1)
        ]
        fixture_items.append(
            {
                "fixture_index": idx,
                "header": fixture.header,
                "row_count": len(row_payload),
                "rows": row_payload,
            }
        )
        slides.append(
            {
                "slide_type": "fixture_sheet",
                "fixture_index": idx,
                "fixture_count": len(slides_raw),
                "header": fixture.header,
                "subtitle": subtitle,
                "rows": row_payload,
            }
        )

    for idx, slide in enumerate(slides, start=1):
        slide["slide_number"] = idx
        slide["slide_count"] = len(slides)

    manifest = {
        "version": 1,
        "channel": "instagram",
        "format": "carousel",
        "variant": "by_fixture_text_prototype",
        "source": "by_fixture_text",
        "slot": slot,
        "scheduled_for": scheduled_for,
        "label": label,
        "title": title,
        "subtitle": subtitle,
        "intro_lines": intro_lines,
        "outro_lines": outro_lines,
        "content_path": str(content_path),
        "counts": {
            "fixture_count": len(fixture_items),
            "total_rows": sum(item["row_count"] for item in fixture_items),
            "max_rows_per_fixture": max((item["row_count"] for item in fixture_items), default=0),
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
