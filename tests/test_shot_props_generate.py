from __future__ import annotations

import unittest
from datetime import date

from src.shot_props.generate import (
    HIGH_PROB_INTRO,
    HIGH_PROB_MIN_HIT_PCT,
    HIGH_PROB_MIN_ODDS,
    HIGH_PROB_TITLE,
    QualifyingPlayer,
    VALUE_INTRO,
    VALUE_MIN_HIT_PCT,
    VALUE_MIN_ODDS,
    VALUE_TITLE,
    _filter_and_format,
    _best_qualifying_window,
    _recent_started_samples,
    _render_candidate_line,
    _value_scope_dates_for_target,
    _verify_post_matches_candidates,
)


class ShotPropsGenerateTests(unittest.TestCase):
    def test_recent_started_samples_excludes_bench_games(self) -> None:
        raw_values = [1, 0, 0, 4, 5]
        raw_minutes = [90, 12, 0, 78, 90]

        starts = _recent_started_samples(raw_values, raw_minutes)

        self.assertEqual(starts, [(1, 90), (4, 78), (5, 90)])

    def test_recent_started_samples_caps_to_twenty_starts(self) -> None:
        raw_values = list(range(30))
        raw_minutes = [90] * 30

        starts = _recent_started_samples(raw_values, raw_minutes)

        self.assertEqual(len(starts), 20)
        self.assertEqual(starts[0], (0, 90))
        self.assertEqual(starts[-1], (19, 90))

    def test_best_qualifying_window_returns_largest_n(self) -> None:
        candidate = QualifyingPlayer(
            player_id=1,
            player_name="Player A",
            team_id=10,
            team_name="Team A",
            fixture_id=100,
            fixture_label="Team A vs Team B",
            league_id=8,
            league_name="Premier League",
            stat_label="1+ Shot",
            stat_type_id=42,
            market_key="player_shots",
            threshold=1,
            hits=0,
            sample=0,
            odds=2.0,
            started_values=[1, 1, 1, 1, 1, 1, 0, 0, 1, 1],  # 8/10 and 6/7 qualify.
        )
        self.assertEqual(_best_qualifying_window(candidate, 0.8), (8, 10))

    def test_render_candidate_line_uses_surname(self) -> None:
        candidate = QualifyingPlayer(
            player_id=1,
            player_name="Morgan Rogers",
            team_id=10,
            team_name="Aston Villa",
            fixture_id=100,
            fixture_label="Wolves vs Aston Villa",
            league_id=8,
            league_name="Premier League",
            stat_label="1+ SOT",
            stat_type_id=86,
            market_key="player_shots_on_target",
            threshold=1,
            hits=6,
            sample=7,
            odds=1.80,
        )
        self.assertEqual(
            _render_candidate_line(candidate),
            "→ Rogers (Aston Villa) won in 6/7 @1.80",
        )

    def test_value_scope_dates_weekend_behavior(self) -> None:
        self.assertEqual(
            [d.isoformat() for d in _value_scope_dates_for_target(date(2026, 2, 28))],
            ["2026-02-28", "2026-03-01"],
        )
        self.assertEqual(_value_scope_dates_for_target(date(2026, 3, 1)), [])

    def test_verify_post_matches_candidates_detects_missing_line(self) -> None:
        candidates = [
            QualifyingPlayer(
                player_id=1,
                player_name="Player A",
                team_id=10,
                team_name="Team A",
                fixture_id=100,
                fixture_label="Team A vs Team B",
                league_id=8,
                league_name="Premier League",
                stat_label="1+ Shot",
                stat_type_id=42,
                market_key="player_shots",
                threshold=1,
                hits=8,
                sample=10,
                odds=2.00,
            ),
            QualifyingPlayer(
                player_id=2,
                player_name="Player B",
                team_id=11,
                team_name="Team B",
                fixture_id=100,
                fixture_label="Team A vs Team B",
                league_id=8,
                league_name="Premier League",
                stat_label="1+ SOT",
                stat_type_id=86,
                market_key="player_shots_on_target",
                threshold=1,
                hits=9,
                sample=10,
                odds=1.45,
            ),
        ]

        value_post = _filter_and_format(
            candidates,
            min_hit_pct=VALUE_MIN_HIT_PCT,
            min_odds=VALUE_MIN_ODDS,
            title=VALUE_TITLE,
            intro=VALUE_INTRO,
        )
        value_issues = _verify_post_matches_candidates(
            value_post,
            candidates,
            VALUE_MIN_HIT_PCT,
            VALUE_MIN_ODDS,
            "Potential Value",
        )
        self.assertEqual(value_issues, [])

        hp_post = _filter_and_format(
            candidates,
            min_hit_pct=HIGH_PROB_MIN_HIT_PCT,
            min_odds=HIGH_PROB_MIN_ODDS,
            title=HIGH_PROB_TITLE,
            intro=HIGH_PROB_INTRO,
        )
        hp_issues = _verify_post_matches_candidates(
            hp_post,
            candidates,
            HIGH_PROB_MIN_HIT_PCT,
            HIGH_PROB_MIN_ODDS,
            "High Probability",
        )
        self.assertEqual(hp_issues, [])

        broken_hp_post = hp_post.replace("→ B (Team B) won in 9/10 @1.45\n", "", 1)
        broken_issues = _verify_post_matches_candidates(
            broken_hp_post,
            candidates,
            HIGH_PROB_MIN_HIT_PCT,
            HIGH_PROB_MIN_ODDS,
            "High Probability",
        )
        self.assertTrue(any("missing" in issue.lower() for issue in broken_issues))


if __name__ == "__main__":
    unittest.main()
