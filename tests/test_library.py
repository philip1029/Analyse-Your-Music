"""analysis.library (Last.fm 라이브러리 같은 순위·상세 화면 데이터) 테스트. 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis.library import album_detail, artist_detail, ranked_page, track_detail  # noqa: E402


def frame():
    rows = []

    def add(n, artist, album, track, day, source="L"):
        for i in range(n):
            rows.append({"utc_time": f"2026-01-{day:02d} {i % 24:02d}:00:00", "artist": artist, "album": album, "track": track, "source": source})

    add(5, "Pink Floyd", "WYWH", "Have a Cigar", 3)
    add(3, "Pink Floyd", "WYWH", "Wish You Were Here", 4)
    add(2, "Pink Floyd", "Animals", "Dogs", 5, "A")
    add(4, "VISUAL ARTS / Key", "Air OST", "Tori No Uta", 6)
    add(2, "LIA & VISUAL ARTS / Key", "Air OST", "Tori No Uta", 7)
    add(2, "Melvins", "Melvins", "Untitled", 8)
    add(3, "Radiohead", "Kid A", "Untitled", 9)
    add(1, "", "Solo", "Intro", 10)
    return pd.DataFrame(rows)


class RankedPageTest(unittest.TestCase):
    def test_artist_ranking_counts_and_totals(self):
        r = ranked_page(frame(), "artist")
        self.assertEqual([(i["name"], i["count"]) for i in r["items"][:2]], [("Pink Floyd", 10), ("VISUAL ARTS / Key", 4)])
        self.assertEqual((r["total"], r["total_plays"]), (5, 22))         # 빈 아티스트는 순위에서 제외, 전체 재생 수에는 포함

    def test_track_ranking_separates_same_title_and_merges_credit_variants(self):
        r = ranked_page(frame(), "track")
        by = {(i["artist"], i["name"]): i["count"] for i in r["items"]}
        self.assertEqual(by[("VISUAL ARTS / Key", "Tori No Uta")], 6)        # 크레딧 표기 차이는 합침
        self.assertEqual((by[("Melvins", "Untitled")], by[("Radiohead", "Untitled")]), (2, 3))
        self.assertEqual(next(i for i in r["items"] if i["name"] == "Have a Cigar")["album"], "WYWH")

    def test_album_ranking_and_pagination(self):
        full = ranked_page(frame(), "album", 0, 50)
        page = ranked_page(frame(), "album", 1, 2)
        self.assertEqual([i["name"] for i in page["items"]], [i["name"] for i in full["items"][1:3]])
        self.assertEqual((page["offset"], page["total"]), (1, full["total"]))


class DetailTest(unittest.TestCase):
    def test_artist_detail(self):
        d = artist_detail(frame(), "Pink Floyd")
        self.assertEqual((d["scrobbles"], d["albums_count"], d["tracks_count"]), (10, 2, 3))
        self.assertEqual(d["albums"][0], {"name": "WYWH", "artist": "Pink Floyd", "count": 8})
        self.assertEqual(d["tracks"][0]["name"], "Have a Cigar")
        self.assertEqual(d["tracks"][0]["album"], "WYWH")
        self.assertIsNone(artist_detail(frame(), "Nobody"))

    def test_album_detail_includes_credit_variants(self):
        d = album_detail(frame(), "VISUAL ARTS / Key", "Air OST")
        self.assertEqual((d["scrobbles"], d["tracks_count"]), (6, 1))
        self.assertIsNone(album_detail(frame(), "Nobody", "Air OST"))

    def test_track_detail_lists_plays_newest_first_with_paging(self):
        d = track_detail(frame(), "Pink Floyd", "Have a Cigar", limit=2)
        self.assertEqual((d["scrobbles"], d["first_played"], d["last_played"], d["album"]), (5, "2026-01-03", "2026-01-03", "WYWH"))
        self.assertEqual(len(d["plays"]), 2)
        times = [p["time"] for p in d["plays"]]
        self.assertEqual(times, sorted(times, reverse=True))
        rest = track_detail(frame(), "Pink Floyd", "Have a Cigar", offset=2, limit=10)
        self.assertEqual(len(rest["plays"]), 3)

    def test_track_detail_separates_same_title_other_artist(self):
        self.assertEqual(track_detail(frame(), "Melvins", "Untitled")["scrobbles"], 2)
        self.assertEqual(track_detail(frame(), "Radiohead", "Untitled")["scrobbles"], 3)

    def test_track_detail_source_flag_and_missing(self):
        d = track_detail(frame(), "Pink Floyd", "Dogs")
        self.assertEqual({p["source"] for p in d["plays"]}, {"A"})
        self.assertIsNone(track_detail(frame(), "Pink Floyd", "Nope"))


if __name__ == "__main__":
    unittest.main()
