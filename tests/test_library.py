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


def credit_frame():
    """Tori no Uta 가 크레딧 표기·대소문자가 다르게 두 아티스트 밑에 있는 경우 (실제 데이터에서 곡 페이지가 안 열리던 사례)."""
    rows = []
    for i in range(5):
        rows.append({"utc_time": f"2026-02-0{i + 1} 00:00:00", "artist": "LIA & VISUAL ARTS / Key", "album": "Air OST", "track": "Tori no Uta", "source": "L"})
    for i in range(2):
        rows.append({"utc_time": f"2026-03-0{i + 1} 00:00:00", "artist": "VISUAL ARTS / Key", "album": "Air OST", "track": "Tori no uta", "source": "A"})
    rows.append({"utc_time": "2026-03-05 00:00:00", "artist": "VISUAL ARTS / Key", "album": "Air OST", "track": "Hane", "source": "A"})
    return pd.DataFrame(rows)


class CreditClusterDetailTest(unittest.TestCase):
    def test_track_opens_from_either_credit_spelling_and_any_letter_case(self):
        for artist, title in (("VISUAL ARTS / Key", "Tori no Uta"), ("LIA & VISUAL ARTS / Key", "Tori no uta"), ("VISUAL ARTS / Key", "TORI NO UTA")):
            d = track_detail(credit_frame(), artist, title)
            self.assertIsNotNone(d, (artist, title))
            self.assertEqual((d["scrobbles"], d["name"], d["artist"]), (7, "Tori no Uta", "LIA & VISUAL ARTS / Key"))

    def test_album_page_merges_case_variants_and_its_tracks_open(self):
        album = album_detail(credit_frame(), "VISUAL ARTS / Key", "Air OST")
        self.assertEqual((album["scrobbles"], album["tracks_count"]), (8, 2))
        top = album["tracks"][0]
        self.assertEqual((top["name"], top["count"]), ("Tori no Uta", 7))
        self.assertEqual(track_detail(credit_frame(), top["artist"], top["name"])["scrobbles"], top["count"])   # 목록 -> 상세가 같은 항목

    def test_every_ranked_item_opens_with_the_same_count(self):
        df = credit_frame()
        for category, fn in (("track", track_detail), ("album", album_detail)):
            for it in ranked_page(df, category)["items"]:
                d = fn(df, it["artist"], it["name"])
                self.assertEqual(d["scrobbles"], it["count"], (category, it))

    def test_track_page_can_be_limited_to_one_album(self):
        df = credit_frame()
        df = pd.concat([df, pd.DataFrame([{"utc_time": "2026-04-01 00:00:00", "artist": "VISUAL ARTS / Key", "album": "AIR 16 bit Arrangements", "track": "Tori no Uta", "source": "L"}])], ignore_index=True)
        every = track_detail(df, "VISUAL ARTS / Key", "Tori no Uta")
        only = track_detail(df, "VISUAL ARTS / Key", "Tori no Uta", album="air OST")
        self.assertEqual((every["scrobbles"], every["scope_album"]), (8, None))
        self.assertEqual({a["name"]: a["count"] for a in every["albums"]}, {"Air OST": 7, "AIR 16 bit Arrangements": 1})
        self.assertEqual((only["scrobbles"], only["scope_album"], only["album"]), (7, "Air OST", "Air OST"))
        self.assertEqual({p["album"] for p in only["plays"]}, {"Air OST"})
        self.assertEqual(len(only["albums"]), 2)                      # 앨범별 내역은 범위와 무관하게 전체
        self.assertIsNone(track_detail(df, "VISUAL ARTS / Key", "Tori no Uta", album="No Such Album"))

    def test_album_scope_count_matches_the_album_page(self):
        df = credit_frame()
        top = album_detail(df, "VISUAL ARTS / Key", "Air OST")["tracks"][0]
        self.assertEqual(track_detail(df, top["artist"], top["name"], album="Air OST")["scrobbles"], top["count"])

    def test_artist_page_reports_first_and_last_played_dates_in_kst(self):
        d = artist_detail(credit_frame(), "VISUAL ARTS / Key")
        self.assertEqual((d["first_played"], d["last_played"]), ("2026-03-01", "2026-03-05"))
        late = pd.DataFrame([{"utc_time": "2026-04-01 15:00:00", "artist": "X", "album": "Al", "track": "T", "source": "L"}])
        self.assertEqual(artist_detail(late, "X")["first_played"], "2026-04-02")             # UTC 15:00 = KST 다음 날 00:00

    def test_monthly_counts_fill_empty_months_for_artist_album_and_track(self):
        rows = [{"utc_time": t, "artist": "X", "album": "Al", "track": "T", "source": "L"}
                for t in ("2026-01-05 03:00:00", "2026-01-06 03:00:00", "2026-04-01 03:00:00")]
        df = pd.DataFrame(rows)
        want = {"months": ["2026-01", "2026-02", "2026-03", "2026-04"], "counts": [2, 0, 0, 1]}
        self.assertEqual(artist_detail(df, "X")["monthly"], want)
        self.assertEqual(album_detail(df, "X", "Al")["monthly"], want)
        self.assertEqual(track_detail(df, "X", "T")["monthly"], want)

    def test_album_page_reports_first_and_last_played_dates_in_kst(self):
        df = credit_frame()
        a = album_detail(df, "VISUAL ARTS / Key", "Air OST")
        self.assertEqual((a["first_played"], a["last_played"]), ("2026-02-01", "2026-03-05"))
        # UTC 15:00 이후는 한국 시간으로 다음 날이다
        late = pd.DataFrame([{"utc_time": "2026-04-01 16:00:00", "artist": "X", "album": "Late", "track": "T", "source": "L"}])
        self.assertEqual(album_detail(late, "X", "Late")["first_played"], "2026-04-02")

    def test_artist_page_counts_case_variants_once(self):
        d = artist_detail(credit_frame(), "VISUAL ARTS / Key")
        self.assertEqual((d["tracks_count"], d["tracks"][0]["name"]), (2, "Tori no uta"))


if __name__ == "__main__":
    unittest.main()
