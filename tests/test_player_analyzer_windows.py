from __future__ import annotations

import os
import unittest


# `src.player_analyzer` imports `src.data_fetcher`, which expects this at import time.
os.environ.setdefault("SUPABASE_DB_URL", "postgresql://user:pass@localhost:5432/db")

from src.player_analyzer import _largest_qualifying_window, _qualifying_hits


class PlayerAnalyzerWindowTests(unittest.TestCase):
    def test_largest_qualifying_window_prefers_biggest_n(self) -> None:
        # 80% rule: qualifies at n=6 (5/6), fails at n=7 (5/7), qualifies again at n=10 (8/10).
        values = [1, 1, 1, 1, 0, 1, 0, 1, 1, 1]

        best = _largest_qualifying_window(values, threshold=1)

        self.assertEqual(best, (8, 10))

    def test_largest_qualifying_window_requires_min_six_games(self) -> None:
        self.assertIsNone(_largest_qualifying_window([1, 1, 1, 1, 1], threshold=1))

    def test_qualifying_hits_uses_largest_window_per_threshold(self) -> None:
        values = [2, 2, 2, 1, 2, 2, 0, 2]

        hits = _qualifying_hits(values, thresholds=[1, 2, 3], stat_key="shots")

        self.assertEqual([(h.threshold, h.wins, h.total) for h in hits], [(1, 7, 8), (2, 5, 6)])

    def test_regression_user_reported_examples_match_recent_window_logic(self) -> None:
        buendia_fouls_committed = [2, 0, 1, 2, 1, 3, 0, 2, 2, 2, 1, 0, 0]
        rogers_sot = [0, 1, 1, 1, 2, 2, 2, 0, 0, 0, 3, 2, 1, 0, 1, 2, 0, 1, 0, 1]
        rogers_shots = [2, 4, 1, 4, 2, 6, 3, 2, 2, 2, 7, 5, 1, 0, 3, 3, 1, 3, 0, 1]

        self.assertEqual(_largest_qualifying_window(buendia_fouls_committed, threshold=1), (9, 11))
        self.assertEqual(_largest_qualifying_window(rogers_sot, threshold=1), (6, 7))
        self.assertEqual(_largest_qualifying_window(rogers_shots, threshold=2), (13, 16))


if __name__ == "__main__":
    unittest.main()
