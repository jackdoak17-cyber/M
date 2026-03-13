from __future__ import annotations

import unittest

from src.posting.post_to_x import _build_weekend_fixture_thread


class WeekendFixtureThreadSplitTests(unittest.TestCase):
    def test_splits_into_intro_plus_first_fixture_and_footer_on_last_fixture(self) -> None:
        content = (
            "All of today's Premier League stat list by fixture. All data driven based on recent form\n\n"
            "If you find this useful please leave a like and remember to bookmark\n\n"
            "Burnley vs Bournemouth - 3:00pm\n\n"
            "A. Scott 2+ shots (won in 7/8)\n"
            "M. Tavernier 2+ shots (won in 11/13)\n\n"
            "Arsenal vs Chelsea - 4:30pm\n\n"
            "B. Saka 2+ shots (won in 11/13)\n"
            "Arsenal 3+ corners (won in 19/20)\n\n"
            "Make sure you bookmark for later\n\n"
            "Good luck with your bets"
        )

        chunks = _build_weekend_fixture_thread(content)

        self.assertIsNotNone(chunks)
        assert chunks is not None
        self.assertEqual(len(chunks), 2)
        self.assertIn("All of today's Premier League stat list", chunks[0])
        self.assertIn("Burnley vs Bournemouth - 3:00pm", chunks[0])
        self.assertTrue(chunks[1].startswith("Arsenal vs Chelsea - 4:30pm"))
        self.assertIn("Arsenal vs Chelsea - 4:30pm", chunks[1])
        self.assertTrue(chunks[1].endswith("Make sure you bookmark for later\n\nGood luck with your bets"))

    def test_returns_none_when_no_fixture_headings_exist(self) -> None:
        content = (
            "All of today's Premier League stat list by fixture. All data driven based on recent form\n\n"
            "No fixture headings are present in this sample."
        )
        self.assertIsNone(_build_weekend_fixture_thread(content))

    def test_keeps_fixture_blocks_when_no_footer_exists(self) -> None:
        content = (
            "Intro line\n\n"
            "Team A vs Team B - 2:00pm\n\n"
            "A. One 1+ shots (won in 7/8)\n\n"
            "Team C vs Team D - 4:30pm\n\n"
            "C. Three 1+ foul won (won in 8/10)\n"
        )

        chunks = _build_weekend_fixture_thread(content)

        self.assertIsNotNone(chunks)
        assert chunks is not None
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].startswith("Intro line\n\nTeam A vs Team B - 2:00pm"))
        self.assertTrue(chunks[1].startswith("Team C vs Team D - 4:30pm"))


if __name__ == "__main__":
    unittest.main()
