"""Overview 통계 카드(증감·미니 막대) 테스트 (합성 데이터). 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis.overview_cards import BARS, RECENT_DAYS, build_overview_cards  # noqa: E402


def frame(days=90, per_day=2, start="2026-01-01"):
    """매일 per_day 곡, 하루마다 새 아티스트·앨범·트랙 (KST 정오 = UTC 03시)."""
    rows = []
    for i, day in enumerate(pd.date_range(start, periods=days)):
        for j in range(per_day):
            rows.append({"utc_time": f"{day:%Y-%m-%d} 03:0{j}:00", "artist": f"A{i}", "album": f"Al{i}", "track": f"T{i}-{j}", "source": "L"})
    return pd.DataFrame(rows)


class RangeModeTest(unittest.TestCase):
    def test_range_compares_with_the_previous_window_of_equal_length(self):
        r = build_overview_cards(frame(), "2026-02-01", "2026-02-28")          # 28일, 직전 28일 = 1/4 ~ 1/31
        c = r["cards"]
        self.assertEqual((r["mode"], c["scrobbles"]["value"], c["scrobbles"]["prev"]), ("range", 56, 56))
        self.assertEqual((c["artists"]["value"], c["artists"]["prev"]), (28, 28))
        self.assertEqual(c["scrobbles"]["delta_pct"], 0.0)

    def test_delta_percentage_when_the_window_grows(self):
        df = pd.concat([frame(days=31, per_day=1), frame(days=28, per_day=3, start="2026-02-01")], ignore_index=True)
        c = build_overview_cards(df, "2026-02-01", "2026-02-28")["cards"]       # 직전 28일: 28회, 이번: 84회
        self.assertEqual((c["scrobbles"]["prev"], c["scrobbles"]["value"], c["scrobbles"]["delta_pct"]), (28, 84, 200.0))

    def test_no_previous_data_means_no_delta(self):
        r = build_overview_cards(frame(), "2026-01-01", "2026-01-15")
        for card in r["cards"].values():
            self.assertEqual(card["prev"], 0)
            self.assertIsNone(card["delta_pct"])

    def test_mini_bars_split_the_window_into_equal_parts(self):
        r = build_overview_cards(frame(), "2026-02-01", "2026-03-30")          # 58일
        bars = r["cards"]["scrobbles"]["bars"]
        self.assertEqual(len(bars), BARS)
        self.assertEqual(sum(bars), r["cards"]["scrobbles"]["value"])          # 구간이 겹치거나 빠지지 않는다

    def test_open_ended_range_uses_data_edges(self):
        r = build_overview_cards(frame(), start="2026-03-01")
        self.assertEqual((r["mode"], r["label"]), ("range", "2026-03-01 ~ 2026-03-31"))


class RecentModeTest(unittest.TestCase):
    def test_all_time_shows_totals_and_recent_change(self):
        df = frame(days=90)
        r = build_overview_cards(df)
        c = r["cards"]["scrobbles"]
        self.assertEqual((r["mode"], c["value"]), ("recent", 180))
        self.assertEqual(c["prev"], RECENT_DAYS * 2)
        self.assertEqual(c["delta_pct"], 0.0)                                  # 최근 30일 = 직전 30일 = 60
        self.assertEqual(len(c["bars"]), BARS)

    def test_recent_change_reflects_a_busier_last_month(self):
        old, new = frame(days=60, per_day=1, start="2026-01-01"), frame(days=30, per_day=3, start="2026-03-02")
        r = build_overview_cards(pd.concat([old, new], ignore_index=True))
        self.assertEqual(r["cards"]["scrobbles"]["delta_pct"], 200.0)           # 직전 30일 30 -> 최근 30일 90

    def test_empty_frame(self):
        self.assertEqual(build_overview_cards(frame().iloc[0:0])["cards"], {})


if __name__ == "__main__":
    unittest.main()
