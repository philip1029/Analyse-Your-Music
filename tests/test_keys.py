"""analysis.keys (아티스트+이름 집계 키) 테스트. 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis.keys import key_series, unique_count  # noqa: E402
from app.analysis.discovery import compute_discovery  # noqa: E402


def frame():
    return pd.DataFrame({
        "uts": [1, 2, 3, 4, 5],
        "utc_time": ["2026-01-01 00:00:00", "2026-01-02 00:00:00", "2026-02-01 00:00:00", "2026-02-02 00:00:00", "2026-02-03 00:00:00"],
        "artist": ["Melvins", "Radiohead", "Radiohead", "", None],
        "album": ["Melvins", "Kid A", "Kid A", "", "Solo"],
        "track": ["Untitled", "Untitled", "Untitled", "Intro", "Intro"],
    })


class KeysTest(unittest.TestCase):
    def test_same_title_different_artists_get_different_keys(self):
        k = key_series(frame(), "track")
        self.assertEqual(list(k), ["Melvins - Untitled", "Radiohead - Untitled", "Radiohead - Untitled", "Intro", "Intro"])

    def test_empty_name_becomes_empty_key_and_is_not_counted(self):
        df = frame()
        df.loc[0, "album"] = ""
        self.assertEqual(key_series(df, "album").iloc[0], "")
        self.assertEqual(unique_count(df, "album"), 2)      # "Radiohead - Kid A", "Solo"

    def test_unique_count_splits_same_title_by_artist(self):
        self.assertEqual(unique_count(frame(), "track"), 3)   # Melvins/Radiohead Untitled + Intro

    def test_artist_column_is_unchanged(self):
        self.assertEqual(list(key_series(frame(), "artist"))[:2], ["Melvins", "Radiohead"])

    def test_discovery_counts_second_artists_same_titled_track_as_new(self):
        d = compute_discovery(frame())
        self.assertEqual(d["track"]["total_new"], 3)
        self.assertEqual(d["track"]["months"], ["2026-01", "2026-02"])


if __name__ == "__main__":
    unittest.main()
