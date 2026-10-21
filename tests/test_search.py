"""analysis.search (아티스트·앨범·곡 이름 검색) 테스트. 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis.search import search_library  # noqa: E402


def frame():
    rows = []

    def add(n, artist, album, track):
        for i in range(n):
            rows.append({"utc_time": f"2026-01-03 {i % 24:02d}:00:00", "artist": artist, "album": album, "track": track, "source": "L"})

    add(5, "Pink Floyd", "Wish You Were Here", "Have a Cigar")
    add(3, "Pink Floyd", "Wish You Were Here", "Wish You Were Here")
    add(2, "Pink Floyd", "Animals", "Dogs")
    add(4, "Floyd Cramer", "Last Date", "Last Date")
    add(2, "Radiohead", "Kid A", "Untitled")
    add(1, "", "Solo", "Intro")
    return pd.DataFrame(rows)


class SearchTest(unittest.TestCase):
    def test_artist_prefix_before_contains_and_by_plays(self):
        r = search_library(frame(), "floyd")
        # "Floyd Cramer"는 앞부분 일치, "Pink Floyd"는 포함 → 앞부분 일치가 먼저
        self.assertEqual([a["name"] for a in r["artists"]], ["Floyd Cramer", "Pink Floyd"])
        self.assertEqual(r["artists"][1]["count"], 10)

    def test_case_spacing_and_symbols_ignored(self):
        r = search_library(frame(), "  PINK-floyd ")
        self.assertEqual(r["artists"][0]["name"], "Pink Floyd")

    def test_track_found_with_artist_text_and_has_album(self):
        r = search_library(frame(), "pink floyd wish")
        self.assertEqual(r["tracks"][0]["name"], "Wish You Were Here")
        self.assertEqual(r["tracks"][0]["artist"], "Pink Floyd")
        self.assertEqual(r["tracks"][0]["album"], "Wish You Were Here")
        self.assertEqual(r["albums"][0]["name"], "Wish You Were Here")

    def test_no_match_across_artist_name_boundary(self):
        # "Radiohead" + "Kid A" 를 이어 붙이면 "headkid" 가 있지만, 이름 경계를 가로지르는 일치는 찾지 않는다
        r = search_library(frame(), "headk")
        self.assertEqual((r["albums"], r["tracks"]), ([], []))

    def test_exact_match_comes_first(self):
        r = search_library(frame(), "wish you were here")
        names = [t["name"] for t in r["tracks"]]
        self.assertEqual(names[0], "Wish You Were Here")

    def test_empty_and_unmatched_queries(self):
        df = frame()
        self.assertEqual(search_library(df, "")["artists"], [])
        self.assertEqual(search_library(df, "   ")["tracks"], [])
        r = search_library(df, "zzzz")
        self.assertEqual((r["artists"], r["albums"], r["tracks"]), ([], [], []))

    def test_limit(self):
        r = search_library(frame(), "o", limit=1)
        self.assertLessEqual(len(r["artists"]), 1)
        self.assertLessEqual(len(r["tracks"]), 1)


if __name__ == "__main__":
    unittest.main()
