from __future__ import annotations

import os
import unittest


# `src.team_analyzer` imports `src.data_fetcher`, which expects this at import time.
os.environ.setdefault("SUPABASE_DB_URL", "postgresql://user:pass@localhost:5432/db")

from src.team_analyzer import _largest_qualifying_window


class TeamAnalyzerWindowTests(unittest.TestCase):
    def test_largest_qualifying_window_prefers_biggest_n(self) -> None:
        # min team sample remains 5.
        values = [1, 1, 1, 0, 1, 1, 1]  # >=1 qualifies at n=5 (4/5) and again at n=7 (6/7)

        best = _largest_qualifying_window(values, threshold=1)

        self.assertEqual(best, (6, 7))

    def test_largest_qualifying_window_requires_min_five_games(self) -> None:
        self.assertIsNone(_largest_qualifying_window([1, 1, 1, 1], threshold=1))

    def test_largest_qualifying_window_returns_none_if_no_window_hits_rate(self) -> None:
        values = [1, 0, 1, 0, 1, 0, 1]

        self.assertIsNone(_largest_qualifying_window(values, threshold=1))


if __name__ == "__main__":
    unittest.main()
