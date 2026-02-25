from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any


SHOT_PROPS_INSTAGRAM_DIR = Path("output/shot_props/instagram")


@dataclass(frozen=True)
class InstagramManifestRef:
    post_type: str
    scheduled_for: date
    path: Path


def shot_props_manifest_path(post_type: str, scheduled_for: date) -> Path:
    if post_type not in {"potential_value", "high_probability"}:
        raise ValueError(f"Unsupported post_type: {post_type}")
    suffix = "potential_value" if post_type == "potential_value" else "high_probability"
    return SHOT_PROPS_INSTAGRAM_DIR / f"{scheduled_for.isoformat()}_{suffix}.json"


def resolve_shot_props_manifest_for_target(post_type: str, target_date: date) -> InstagramManifestRef:
    """Resolve manifest by shot-props target date.

    `target_date` is the fixture date for the generator. Potential value posts are scheduled for the day before.
    """
    if post_type == "potential_value":
        scheduled_for = target_date - timedelta(days=1)
    elif post_type == "high_probability":
        scheduled_for = target_date
    else:
        raise ValueError(f"Unsupported post_type: {post_type}")

    path = shot_props_manifest_path(post_type, scheduled_for)
    return InstagramManifestRef(post_type=post_type, scheduled_for=scheduled_for, path=path)


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def manifest_summary(manifest: dict[str, Any]) -> str:
    counts = manifest.get("counts") or {}
    sections = (counts.get("by_section") or {})
    parts = [f"{k}={v}" for k, v in sections.items()]
    section_summary = ", ".join(parts) if parts else "no sections"
    return (
        f"{manifest.get('post_type')} scheduled_for={manifest.get('scheduled_for')} "
        f"slides={len(manifest.get('slides') or [])} rows={counts.get('total_rows', 0)} "
        f"({section_summary})"
    )

