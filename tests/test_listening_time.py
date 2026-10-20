"""청취 시간(스크롭 횟수 x 곡 길이) 계산 테스트 (합성 데이터, 임시 길이 캐시). 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis import library as lib  # noqa: E402
from app.analysis import listening_time as lt  # noqa: E402
from app.lastfm import durations as d  # noqa: E402


def frame():
    rows = []

    def add(n, artist, album, track, day):
        for i in range(n):
            rows.append({"utc_time": f"2026-01-{day:02d} {i % 20:02d}:00:00", "artist": artist, "album": album, "track": track, "source": "L"})

    add(10, "Short", "S", "Quick", 1)         # 100초 x 10  = 1000초
    add(2, "Long", "L", "Epic", 2)            # 1200초 x 2  = 2400초
    add(3, "Unknown", "U", "Mystery", 3)      # 길이 모름
    add(2, "Glitch", "G", "Blip", 3)          # 길이 5초 -> 모르는 것으로 취급
    return pd.DataFrame(rows)


class TimeTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / d.CACHE_NAME
        d.save_cache(path, {
            d.cache_key("Short", "Quick"): {"sec": 100, "src": "apple", "tried": 1},
            d.cache_key("Long", "Epic"): {"sec": 1200, "src": "apple", "tried": 1},
            d.cache_key("Glitch", "Blip"): {"sec": 5, "src": "lastfm", "tried": 1},
        })
        self.lookup = d.DurationLookup(path)
        self.patches = [mock.patch.object(lt, "durations", self.lookup), mock.patch.object(lib, "durations", self.lookup)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()


class AttachAndTotalsTest(TimeTestBase):
    def test_row_durations_and_short_values_are_treated_as_unknown(self):
        df = lt.attach_durations(frame())
        self.assertEqual(df["dur_sec"].dropna().unique().tolist(), [100.0, 1200.0])
        self.assertTrue(df[df["track"] == "Blip"]["dur_sec"].isna().all())          # 5초 < MIN_TRACK_SEC
        self.assertTrue(df[df["track"] == "Mystery"]["dur_sec"].isna().all())

    def test_total_seconds_and_coverage(self):
        df = frame()
        self.assertEqual(lt.total_seconds(df), 10 * 100 + 2 * 1200)
        self.assertAlmostEqual(lt.coverage(df), 12 / 17)

    def test_attach_is_idempotent_and_handles_empty(self):
        df = lt.attach_durations(frame())
        self.assertIs(lt.attach_durations(df), df)
        self.assertEqual(lt.total_seconds(frame().iloc[0:0]), 0)
        self.assertEqual(lt.coverage(frame().iloc[0:0]), 0.0)

    def test_weights_are_minutes_for_time_and_one_for_plays(self):
        df = frame()
        self.assertEqual(lt.weights(df, "plays").sum(), len(df))
        self.assertAlmostEqual(lt.weights(df, "time").sum(), (1000 + 2400) / 60)

    def test_fmt_hm(self):
        self.assertEqual(lt.fmt_hm(35 * 60), "35분")
        self.assertEqual(lt.fmt_hm(3600 * 12 + 300), "12시간 5분")


class SummaryTest(TimeTestBase):
    def test_summary_numbers(self):
        s = lt.time_summary(frame())
        self.assertEqual(s["total_seconds"], 3400)
        self.assertEqual((s["total_plays"], s["known_plays"]), (17, 12))
        self.assertEqual((s["days"], s["active_days"]), (3, 3))                        # 1월 1일 ~ 3일
        self.assertEqual(s["avg_seconds_per_day"], 3400 // 3)
        self.assertEqual(s["busiest_day"], {"date": "2026-01-02", "seconds": 2400, "plays": 2})

    def test_empty_summary(self):
        s = lt.time_summary(frame().iloc[0:0])
        self.assertEqual((s["total_seconds"], s["busiest_day"]), (0, None))


class RankingTest(TimeTestBase):
    def test_time_ranking_differs_from_play_ranking(self):
        by_plays = lib.ranked_page(frame(), "artist", 0, 10, "plays")["items"]
        by_time = lib.ranked_page(frame(), "artist", 0, 10, "time")["items"]
        self.assertEqual(by_plays[0]["name"], "Short")                                  # 10회
        self.assertEqual((by_time[0]["name"], by_time[0]["seconds"], by_time[0]["count"]), ("Long", 2400, 2))
        self.assertNotIn("seconds", by_plays[0])

    def test_track_and_album_time_ranking(self):
        for cat, first in (("track", "Epic"), ("album", "L")):
            items = lib.ranked_page(frame(), cat, 0, 10, "time")["items"]
            self.assertEqual(items[0]["name"], first)
            self.assertEqual(items[0]["seconds"], 2400)

    def test_detail_pages_report_total_seconds(self):
        self.assertEqual(lib.artist_detail(frame(), "Short")["seconds"], 1000)
        self.assertEqual(lib.album_detail(frame(), "Long", "L")["seconds"], 2400)
        self.assertEqual(lib.track_detail(frame(), "Short", "Quick")["seconds"], 1000)
        self.assertEqual(lib.track_detail(frame(), "Unknown", "Mystery")["seconds"], 0)


if __name__ == "__main__":
    unittest.main()
