"""analysis.keys (아티스트+이름 집계 키) 테스트. 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis.keys import key_series, resolve_keys, unique_count  # noqa: E402
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


def albums(*pairs):
    """(아티스트, 앨범) 쌍 목록으로 만든 데이터프레임."""
    return pd.DataFrame({"artist": [a for a, _ in pairs], "album": [b for _, b in pairs], "track": ["t"] * len(pairs)})


class CreditClusterTest(unittest.TestCase):
    def test_credit_variants_of_the_same_album_are_one_item(self):
        df = albums(*[("VISUAL ARTS / Key", "Air OST")] * 5, *[("LIA & VISUAL ARTS / Key", "Air OST")] * 3, ("riya & VISUAL ARTS / Key", "Air OST"))
        keys, reps = resolve_keys(df, "album")
        self.assertEqual(set(keys), {"VISUAL ARTS / Key - Air OST"})       # 가장 많이 쓰인 표기가 대표
        self.assertEqual(set(reps), {"VISUAL ARTS / Key"})
        self.assertEqual(unique_count(df, "album"), 1)

    def test_unrelated_artists_with_the_same_album_name_stay_separate(self):
        df = albums(("Jim O'Rourke", "Eureka"), ("Jim O'Rourke", "Eureka"), ("키노코 테이코쿠", "Eureka"))
        self.assertEqual(unique_count(df, "album"), 2)

    def test_feat_and_with_credits_join_the_main_artist(self):
        df = albums(("Kanye West", "College Dropout"), ("Twista, Kanye West & Jamie Foxx", "College Dropout"), ("Outkast", "Stankonia"), ("Outkast with Erykah Badu", "Stankonia"))
        self.assertEqual(unique_count(df, "album"), 2)

    def test_slash_without_spaces_is_not_a_separator(self):
        df = albums(("AC/DC", "Album"), ("DC", "Album"))
        self.assertEqual(unique_count(df, "album"), 2)

    def test_rows_without_artist_join_the_largest_cluster(self):
        df = albums(("Oasis", "Morning Glory"), ("Oasis", "Morning Glory"), ("Tim Buckley", "Morning Glory"), ("", "Morning Glory"))
        keys, _ = resolve_keys(df, "album")
        self.assertEqual(list(keys), ["Oasis - Morning Glory"] * 2 + ["Tim Buckley - Morning Glory", "Oasis - Morning Glory"])

    def test_nothing_but_empty_artists_keeps_plain_name(self):
        keys, reps = resolve_keys(albums(("", "Solo")), "album")
        self.assertEqual((list(keys), list(reps)), (["Solo"], [""]))


if __name__ == "__main__":
    unittest.main()
