from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from .manifest_io import (
    load_manifest,
    manifest_summary,
    resolve_shot_props_manifest_for_target,
)
from .renderer import (
    PLAYWRIGHT_PKG_DEFAULT,
    render_carousel_images,
    write_debug_preview_bundle,
)
from .shot_props_manifest import verify_shot_props_carousel_manifest


DEFAULT_RENDER_ROOT = Path("output/shot_props/instagram_render")


def _default_output_dir(manifest: dict, manifest_path: Path | None) -> Path:
    post_type = str(manifest.get("post_type") or "shot_props")
    scheduled_for = str(manifest.get("scheduled_for") or "unknown-date")
    stem = manifest_path.stem if manifest_path else f"{scheduled_for}_{post_type}"
    return DEFAULT_RENDER_ROOT / stem


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render shot-props Instagram carousel from manifest.")
    parser.add_argument("--manifest", help="Path to manifest JSON.")
    parser.add_argument(
        "--post-type",
        choices=["potential_value", "high_probability"],
        help="Resolve manifest from shot-props output using target fixture date.",
    )
    parser.add_argument(
        "--date",
        dest="target_date",
        help="Shot-props target fixture date (YYYY-MM-DD) when using --post-type.",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory for rendered artifacts (defaults to output/shot_props/instagram_render/<manifest>).",
    )
    parser.add_argument(
        "--render-images",
        action="store_true",
        help="Render raster images via Playwright CLI (otherwise writes HTML QA bundle only).",
    )
    parser.add_argument(
        "--image-ext",
        default="jpeg",
        choices=["jpeg", "jpg", "png"],
        help="Image format for Playwright screenshots.",
    )
    parser.add_argument(
        "--playwright-package",
        default=PLAYWRIGHT_PKG_DEFAULT,
        help=f"Playwright npm package spec for npx (default: {PLAYWRIGHT_PKG_DEFAULT}).",
    )
    parser.add_argument(
        "--playwright-channel",
        choices=["chrome", "chrome-beta", "msedge", "msedge-dev"],
        help="Use a locally installed browser channel (avoids Playwright browser download).",
    )
    parser.add_argument(
        "--skip-verify",
        action="store_true",
        help="Skip manifest verification before rendering.",
    )
    return parser.parse_args()


def _resolve_manifest_path(args: argparse.Namespace) -> Path:
    if args.manifest:
        return Path(args.manifest)
    if not args.post_type or not args.target_date:
        raise SystemExit("Provide either --manifest OR (--post-type and --date YYYY-MM-DD).")
    target = date.fromisoformat(args.target_date)
    ref = resolve_shot_props_manifest_for_target(args.post_type, target)
    return ref.path


def main() -> None:
    args = _parse_args()
    manifest_path = _resolve_manifest_path(args)
    if not manifest_path.exists():
        raise SystemExit(f"Manifest not found: {manifest_path}")

    manifest = load_manifest(manifest_path)
    issues = [] if args.skip_verify else verify_shot_props_carousel_manifest(manifest)
    if issues:
        joined = "\n".join(f"- {issue}" for issue in issues)
        raise SystemExit(f"Manifest verification failed for {manifest_path}:\n{joined}")

    output_dir = Path(args.output_dir) if args.output_dir else _default_output_dir(manifest, manifest_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loaded manifest: {manifest_path}")
    print(f"Summary: {manifest_summary(manifest)}")

    if args.render_images:
        rendered = render_carousel_images(
            manifest,
            output_dir,
            manifest_path=manifest_path,
            image_ext=args.image_ext,
            playwright_pkg=args.playwright_package,
            browser_channel=args.playwright_channel,
        )
        print(f"Rendered {len(rendered.slides)} image slides to {output_dir / 'images'}")
        print(f"Render manifest: {output_dir / 'render_manifest.json'}")
    else:
        index_path = write_debug_preview_bundle(manifest, output_dir)
        print(f"Wrote HTML QA preview: {index_path}")
        print(f"Slide HTML files: {output_dir / 'slides_html'}")


if __name__ == "__main__":
    main()
