"""Bar chart race 데이터(누적 순위 변화) 테스트. 합성 기록이라 파일·네트워크가 필요 없다. 실행:
    python3 -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis import race, taste  # noqa: E402


def uts(ts: str) -> int:
    return int(pd.Timestamp(ts, tz="Asia/Seoul").timestamp())


def frame(rows):
    """rows: [(KST 시각, 아티스트, 앨범, 곡)]"""
    return pd.DataFrame([{"uts": uts(t), "artist": a, "album": al, "track": tr} for t, a, al, tr in rows])


class RaceTest(unittest.TestCase):
    def test_monthly_cumulative_with_empty_months_and_kst_boundary(self):
        df = frame([
            ("2025-01-31 23:30:00", "A", "x", "t1"),      # UTC 로는 1월이지만 KST 1월 31일
            ("2025-02-01 00:10:00", "A", "x", "t2"),      # UTC 1월 31일 15:10 이지만 KST 로는 2월
            ("2025-04-10 12:00:00", "B", "y", "t3"),
            ("2025-04-11 12:00:00", "B", "y", "t4"),
            ("2025-04-12 12:00:00", "B", "y", "t5"),
        ])
        r = race.build_race(df, "artist", "month", 3)
        self.assertEqual([p["label"] for p in r["periods"]], ["2025-01", "2025-02", "2025-03", "2025-04"])     # 3월(기록 없음)도 이어서
        by = {e["name"]: e["values"] for e in r["entities"]}
        self.assertEqual(by["A"], [1, 2, 2, 2])
        self.assertEqual(by["B"], [0, 0, 0, 3])
        self.assertEqual([e["name"] for e in r["entities"]], ["B", "A"])                                          # 마지막 값이 큰 순
        for values in by.values():
            self.assertEqual(values, sorted(values))                                                              # 누적이라 줄어들지 않는다

    def test_only_entities_that_were_ever_in_the_top_are_returned(self):
        rows = [(f"2025-01-{d:02d} 10:00:00", "Early", "e", f"e{d}") for d in range(1, 6)]            # 1월에 5번
        rows += [(f"2025-02-{d:02d} 10:00:00", "Late", "l", f"l{d}") for d in range(1, 11)]           # 2월에 10번
        rows += [("2025-02-20 10:00:00", "Rare", "r", "r1")]
        r = race.build_race(frame(rows), "artist", "month", 2)
        self.assertEqual({e["name"] for e in r["entities"]}, {"Early", "Late"})                               # 한 번도 상위 2 안에 못 든 Rare 는 없다
        self.assertEqual(len(race.build_race(frame(rows), "artist", "month", 3)["entities"]), 3)
        self.assertEqual(len(race.build_race(frame(rows), "artist", "month", 3, max_entities=2)["entities"]), 2)

    def test_weekly_periods_start_on_monday(self):
        df = frame([("2025-01-08 10:00:00", "A", "x", "t"), ("2025-01-20 10:00:00", "A", "x", "u")])       # 수요일, 월요일
        r = race.build_race(df, "artist", "week", 3)
        self.assertEqual([p["date"] for p in r["periods"]], ["2025-01-06", "2025-01-13", "2025-01-20"])
        self.assertEqual(r["entities"][0]["values"], [1, 1, 2])

    def test_album_and_track_carry_the_artist(self):
        df = frame([("2025-01-01 10:00:00", "A", "Album One", "Song")] * 3)
        for cat, name in (("album", "Album One"), ("track", "Song")):
            r = race.build_race(df, cat, "month", 3)
            self.assertEqual((r["entities"][0]["name"], r["entities"][0]["artist"], r["entities"][0]["values"]), (name, "A", [3]))

    def test_entities_carry_their_most_played_album_for_cover_lookup(self):
        df = frame([
            ("2025-01-01 10:00:00", "A", "Hit Album", "Song1"), ("2025-01-02 10:00:00", "A", "Hit Album", "Song1"), ("2025-01-03 10:00:00", "A", "Hit Album", "Song2"),
            ("2025-01-04 10:00:00", "A", "Other", "Song3"), ("2025-01-05 10:00:00", "B", "", "NoAlbum"),
        ])
        by = {e["name"]: e for e in race.build_race(df, "artist", "month", 5)["entities"]}
        self.assertEqual((by["A"]["album"], by["A"]["album_artist"]), ("Hit Album", "A"))              # 아티스트: 가장 많이 들은 앨범
        self.assertEqual((by["B"]["album"], by["B"]["album_artist"]), (None, None))                    # 앨범 정보가 없으면 없음
        tracks = {e["name"]: e for e in race.build_race(df, "track", "month", 5)["entities"]}
        self.assertEqual((tracks["Song3"]["album"], tracks["Song3"]["album_artist"]), ("Other", "A"))  # 트랙: 그 곡이 들어 있는 앨범
        albums = {e["name"]: e for e in race.build_race(df, "album", "month", 5)["entities"]}
        self.assertEqual((albums["Hit Album"]["album"], albums["Hit Album"]["album_artist"]), ("Hit Album", "A"))

    def test_tag_race_weights_by_cached_tags_and_reports_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / f"{taste._slugify('Rocker')}.json").write_text(json.dumps([{"name": "Rock", "count": 100}, {"name": "pop", "count": 50}]), encoding="utf-8")
            with mock.patch.object(taste, "CACHE_DIR", cache), mock.patch.object(taste, "resolve_artist_name", side_effect=lambda n: n):
                df = frame([("2025-01-05 10:00:00", "Rocker", "x", "t")] * 2 + [("2025-02-05 10:00:00", "Rocker", "x", "t")] + [("2025-02-06 10:00:00", "Unknown", "x", "t")] * 1)
                r = race.build_race(df, "tag", "month", 3)
        by = {e["name"]: e["values"] for e in r["entities"]}
        self.assertEqual(by["rock"], [2.0, 3.0])
        self.assertEqual(by["pop"], [1.0, 1.5])
        self.assertAlmostEqual(r["coverage"], 0.75)                                                           # 4회 중 캐시에 태그가 있는 3회

    def test_daily_rolling_window_sums_only_the_last_n_days(self):
        rows = [("2025-01-01 10:00:00", "A", "x", "t")] + [("2025-01-02 10:00:00", "A", "x", "t")] * 2 + [("2025-01-04 10:00:00", "A", "x", "t")]
        r = race.build_race(frame(rows), "artist", "day", 3, window=3)
        self.assertEqual(r["window"], 3)
        self.assertEqual([p["date"] for p in r["periods"]], ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"])
        self.assertEqual(r["entities"][0]["values"], [1, 3, 3, 3])          # 4일째는 1일 값(1)이 빠지고 2~4일(2+0+1)
        cumulative = race.build_race(frame(rows), "artist", "day", 3)
        self.assertEqual(cumulative["entities"][0]["values"], [1, 3, 3, 4])

    def test_rolling_keeps_entities_that_peaked_earlier_and_drops_out_later(self):
        rows = [("2025-01-01 10:00:00", "Early", "e", "e")] * 5 + [("2025-01-10 10:00:00", "Late", "l", "l")] * 2
        r = race.build_race(frame(rows), "artist", "day", 1, window=3)
        by = {e["name"]: e["values"] for e in r["entities"]}
        self.assertEqual(by["Early"][0], 5)
        self.assertEqual(by["Early"][-1], 0)                                 # 30일 창 밖으로 나가면 0 이 된다
        self.assertEqual(by["Late"][-1], 2)
        self.assertEqual([e["name"] for e in r["entities"]], ["Early", "Late"])      # 최고 값이 큰 순

    def test_rolling_tag_race_uses_overall_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp)
            (cache / f"{taste._slugify('Rocker')}.json").write_text(json.dumps([{"name": "rock", "count": 100}]), encoding="utf-8")
            with mock.patch.object(taste, "CACHE_DIR", cache), mock.patch.object(taste, "resolve_artist_name", side_effect=lambda n: n):
                rows = [("2025-01-01 10:00:00", "Rocker", "x", "t")] * 2 + [("2025-01-09 10:00:00", "Unknown", "x", "t")] * 2
                r = race.build_race(frame(rows), "tag", "day", 3, window=3)
        self.assertEqual({e["name"]: e["values"][0] for e in r["entities"]}, {"rock": 2.0})
        self.assertEqual({e["name"]: e["values"][-1] for e in r["entities"]}, {"rock": 0.0})
        self.assertAlmostEqual(r["coverage"], 0.5)                                    # 마지막 30일이 아니라 전체 재생 기준

    def test_window_is_clamped(self):
        df = frame([("2025-01-01 10:00:00", "A", "x", "t")])
        self.assertEqual(race.build_race(df, "artist", "day", 3, window=1000)["window"], race.MAX_WINDOW)
        self.assertEqual(race.build_race(df, "artist", "day", 3, window=-5)["window"], 0)

    def test_bad_arguments_and_empty_input(self):
        self.assertIn("error", race.build_race(frame([("2025-01-01 10:00:00", "A", "x", "t")]), "genre"))
        self.assertIn("error", race.build_race(frame([("2025-01-01 10:00:00", "A", "x", "t")]), "artist", "year"))
        self.assertEqual(race.build_race(pd.DataFrame(), "artist")["entities"], [])
        self.assertEqual(race.build_race(None, "artist")["periods"], [])


if __name__ == "__main__":
    unittest.main()
