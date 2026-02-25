from __future__ import annotations

import unittest
from datetime import date

from src.instagram.shot_props_manifest import (
    ThresholdConfig,
    build_shot_props_carousel_manifest,
    verify_shot_props_carousel_manifest,
)
from src.shot_props.generate import QualifyingPlayer


def _player(idx: int, section: str, *, hits: int = 9, sample: int = 10, odds: float = 1.8) -> QualifyingPlayer:
    threshold = 2 if section == "2+ Shots" else 1
    stat_type_id = 86 if section == "1+ SOT" else 42
    market_key = "player_shots_on_target" if section == "1+ SOT" else "player_shots"
    return QualifyingPlayer(
        player_id=idx,
        player_name=f"Player {idx}",
        team_id=100 + idx,
        team_name=f"Team {idx}",
        fixture_id=1000 + idx,
        fixture_label=f"Home {idx} vs Away {idx}",
        league_id=8,
        league_name="Premier League",
        stat_label=section,
        stat_type_id=stat_type_id,
        market_key=market_key,
        threshold=threshold,
        hits=hits,
        sample=sample,
        odds=odds,
    )


class InstagramShotPropsManifestTests(unittest.TestCase):
    def test_build_manifest_paginates_without_losing_rows(self) -> None:
        sections = {
            "1+ Shot": [_player(i, "1+ Shot", odds=1.5 + (i * 0.01)) for i in range(1, 12)],
            "2+ Shots": [_player(i + 100, "2+ Shots") for i in range(1, 3)],
            "1+ SOT": [_player(999, "1+ SOT")],
        }
        manifest = build_shot_props_carousel_manifest(
            post_type="high_probability",
            scheduled_for=date(2026, 2, 28),
            source_target_date=date(2026, 2, 28),
            fixture_dates=[date(2026, 2, 28)],
            title="📊 Today's High Probability Stats & Odds List 🔒",
            intro="test intro",
            threshold_cfg=ThresholdConfig(min_hit_pct=0.9, min_odds=1.3, min_starts=7),
            section_order=["1+ Shot", "2+ Shots", "1+ SOT"],
            sections=sections,
            max_rows_per_section_slide=5,
        )
        self.assertIsNotNone(manifest)
        assert manifest is not None

        # 1 cover + 3 pages (11 rows @5) + 1 page + 1 page = 6 slides total.
        self.assertEqual(len(manifest["slides"]), 6)
        self.assertEqual(manifest["counts"]["total_rows"], 14)
        self.assertEqual(manifest["counts"]["by_section"]["1+ Shot"], 11)
        self.assertEqual(manifest["verification"]["ok"], True)
        self.assertEqual(verify_shot_props_carousel_manifest(manifest), [])

        section_slides = [s for s in manifest["slides"] if s["slide_type"] == "section"]
        self.assertEqual(section_slides[0]["section_label"], "1+ Shot")
        self.assertEqual(section_slides[0]["section_page"], 1)
        self.assertEqual(section_slides[0]["section_pages"], 3)

    def test_manifest_verifier_detects_removed_row(self) -> None:
        sections = {
            "1+ Shot": [_player(1, "1+ Shot"), _player(2, "1+ Shot")],
            "2+ Shots": [],
            "1+ SOT": [],
        }
        manifest = build_shot_props_carousel_manifest(
            post_type="potential_value",
            scheduled_for=date(2026, 2, 27),
            source_target_date=date(2026, 2, 28),
            fixture_dates=[date(2026, 2, 28), date(2026, 3, 1)],
            title="📈 This Weekend's Potential Value Stats & Odds List 📝",
            intro="test intro",
            threshold_cfg=ThresholdConfig(min_hit_pct=0.8, min_odds=1.72, min_starts=7),
            section_order=["1+ Shot", "2+ Shots", "1+ SOT"],
            sections=sections,
            max_rows_per_section_slide=8,
        )
        self.assertIsNotNone(manifest)
        assert manifest is not None

        manifest["slides"][1]["rows"].pop()
        issues = verify_shot_props_carousel_manifest(manifest)
        self.assertTrue(any("mismatch" in issue.lower() for issue in issues))

    def test_combined_weekend_caption_includes_date_range(self) -> None:
        manifest = build_shot_props_carousel_manifest(
            post_type="potential_value",
            scheduled_for=date(2026, 2, 27),
            source_target_date=date(2026, 2, 28),
            fixture_dates=[date(2026, 2, 28), date(2026, 3, 1)],
            title="📈 This Weekend's Potential Value Stats & Odds List 📝",
            intro="test intro",
            threshold_cfg=ThresholdConfig(min_hit_pct=0.8, min_odds=1.72, min_starts=7),
            section_order=["1+ Shot", "2+ Shots", "1+ SOT"],
            sections={"1+ Shot": [_player(1, "1+ Shot")], "2+ Shots": [], "1+ SOT": []},
        )
        self.assertIsNotNone(manifest)
        assert manifest is not None
        self.assertIn("Sat 28 Feb", manifest["caption"])
        self.assertIn("Sun 01 Mar 2026", manifest["caption"])


if __name__ == "__main__":
    unittest.main()

