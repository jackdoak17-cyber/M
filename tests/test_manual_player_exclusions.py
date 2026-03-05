from __future__ import annotations

import os
import tempfile
import unittest
from datetime import date
from pathlib import Path


os.environ.setdefault("SUPABASE_DB_URL", "postgresql://user:pass@localhost:5432/db")

from src import data_fetcher


class ManualPlayerExclusionsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmpdir = tempfile.TemporaryDirectory()
        self._original_file = data_fetcher.MANUAL_AVAILABILITY_FILE
        self._original_env = os.environ.get("MANUAL_EXCLUDED_PLAYER_IDS")
        data_fetcher.MANUAL_AVAILABILITY_FILE = Path(self._tmpdir.name) / "manual_player_exclusions.txt"
        data_fetcher._load_manual_player_exclusions.cache_clear()

    def tearDown(self) -> None:
        if self._original_env is None:
            os.environ.pop("MANUAL_EXCLUDED_PLAYER_IDS", None)
        else:
            os.environ["MANUAL_EXCLUDED_PLAYER_IDS"] = self._original_env
        data_fetcher.MANUAL_AVAILABILITY_FILE = self._original_file
        data_fetcher._load_manual_player_exclusions.cache_clear()
        self._tmpdir.cleanup()

    def test_date_ranged_file_entries_expire_automatically(self) -> None:
        data_fetcher.MANUAL_AVAILABILITY_FILE.write_text(
            "\n".join(
                [
                    "5666458,2026-03-01,2026-03-08 # temporary suspension",
                    "777",
                    "888|2026-03-10|2026-03-12",
                ],
            ),
            encoding="utf-8",
        )

        ids_during = data_fetcher.get_manual_excluded_player_ids(on_date=date(2026, 3, 5))
        ids_after = data_fetcher.get_manual_excluded_player_ids(on_date=date(2026, 3, 11))

        self.assertIn(5666458, ids_during)
        self.assertNotIn(5666458, ids_after)
        self.assertIn(777, ids_during)
        self.assertIn(777, ids_after)
        self.assertNotIn(888, ids_during)
        self.assertIn(888, ids_after)

    def test_env_ids_merge_with_file_entries(self) -> None:
        os.environ["MANUAL_EXCLUDED_PLAYER_IDS"] = "901,902,abc"
        data_fetcher.MANUAL_AVAILABILITY_FILE.write_text(
            "903,2026-03-01,2026-03-31",
            encoding="utf-8",
        )
        data_fetcher._load_manual_player_exclusions.cache_clear()

        ids = data_fetcher.get_manual_excluded_player_ids(on_date=date(2026, 3, 15))

        self.assertEqual(ids, {901, 902, 903})


if __name__ == "__main__":
    unittest.main()
