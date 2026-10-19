"""analysis.consistency (월별 재생 분포로 본 꾸준함) 테스트. 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis.consistency import _stats, compute_consistency, stats_for_keys  # noqa: E402

LABELS = [f"2025-{m:02d}" for m in range(1, 13)]


def rows(artist, track, per_month, year=2025):
    out = []
    for month, n in per_month.items():
        for i in range(n):
            out.append({"utc_time": f"{year}-{month:02d}-{i % 28 + 1:02d} 03:00:00", "artist": artist, "album": "", "track": track})
    return out


class StatsTest(unittest.TestCase):
    def test_even_listening_scores_one(self):
        st = _stats(np.array([5] * 12), LABELS)
        self.assertEqual((st["evenness"], st["bias"], st["active_months"], st["months_since_last"]), (1.0, 0.0, 12, 0))

    def test_single_month_burst_scores_zero_without_negative_zero(self):
        st = _stats(np.array([0, 0, 30, 0, 0, 0, 0, 0, 0, 0, 0, 0]), LABELS)
        self.assertEqual((st["evenness"], st["bias"], st["peak_share"]), (0.0, 1.0, 1.0))
        self.assertEqual(str(st["evenness"]), "0.0")
        self.assertEqual(st["months"], 10)                       # 처음 들은 3월부터 12월까지
        self.assertEqual(st["months_since_last"], 9)

    def test_window_starts_at_first_play_not_dataset_start(self):
        a = _stats(np.array([0, 0, 0, 0, 0, 0, 4, 4, 4, 4, 4, 4]), LABELS)
        self.assertEqual((a["months"], a["evenness"]), (6, 1.0))   # 늦게 발견한 곡이 불리하지 않다

    def test_abandoned_track_scores_lower_than_steady_one(self):
        steady = _stats(np.array([3] * 12), LABELS)
        abandoned = _stats(np.array([12, 12, 12, 0, 0, 0, 0, 0, 0, 0, 0, 0]), LABELS)
        self.assertLess(abandoned["evenness"], steady["evenness"])
        self.assertEqual(abandoned["months_since_last"], 9)

    def test_one_month_window_has_no_evenness(self):
        st = _stats(np.array([0] * 11 + [7]), LABELS)
        self.assertIsNone(st["evenness"])

    def test_no_plays_returns_none(self):
        self.assertIsNone(_stats(np.zeros(12, dtype=int), LABELS))


class ComputeTest(unittest.TestCase):
    def frame(self):
        r = rows("A", "Steady", {m: 2 for m in range(1, 13)})
        r += rows("A", "Burst", {2: 24})
        r += rows("B", "Steady", {1: 1, 12: 1})                  # 곡명만 같은 다른 아티스트
        r += rows("A", "Early", {1: 6, 2: 6, 3: 6})
        return pd.DataFrame(r)

    def test_even_sort_ranks_steady_first_and_biased_sort_puts_burst_first(self):
        df = self.frame()
        even = compute_consistency(df, "track", min_plays=10, min_months=6, sort="even")
        biased = compute_consistency(df, "track", min_plays=10, min_months=6, sort="biased")
        self.assertEqual(even["results"][0]["key"], "A - Steady")
        self.assertEqual([r["key"] for r in biased["results"]], ["A - Burst", "A - Early", "A - Steady"])   # 한 달 몰림 < 3개월 후 사라짐 < 꾸준
        self.assertEqual(even["months"][0], "2025-01")
        self.assertEqual(even["results"][0]["artist"], "A")
        self.assertEqual(even["results"][0]["name"], "Steady")

    def test_same_title_other_artist_is_a_separate_item(self):
        keys = {r["key"] for r in compute_consistency(self.frame(), "track", min_plays=1, min_months=2)["results"]}
        self.assertIn("B - Steady", keys)

    def test_thresholds_filter_items(self):
        res = compute_consistency(self.frame(), "track", min_plays=10, min_months=6)
        self.assertEqual({r["key"] for r in res["results"]}, {"A - Steady", "A - Early", "A - Burst"})   # B - Steady 는 2회뿐이라 제외
        strict = compute_consistency(self.frame(), "track", min_plays=10, min_months=12)
        self.assertEqual([r["key"] for r in strict["results"]], ["A - Steady", "A - Early"])   # 2월에 시작한 Burst 는 11개월이라 제외

    def test_track_results_carry_their_most_played_album(self):
        df = self.frame()
        df.loc[df["track"] == "Steady", "album"] = "Album S"
        df.loc[(df["track"] == "Steady") & (df["artist"] == "A") & (df.index % 5 == 0), "album"] = "Single S"
        res = compute_consistency(df, "track", min_plays=10, min_months=6)
        self.assertEqual({r["key"]: r.get("album") for r in res["results"]}["A - Steady"], "Album S")

    def test_empty_frame(self):
        res = compute_consistency(pd.DataFrame(columns=["utc_time", "artist", "album", "track"]), "track")
        self.assertEqual(res["results"], [])

    def test_stats_for_keys_skips_unknown_keys(self):
        st, labels = stats_for_keys(self.frame(), "track", ["A - Steady", "nope"])
        self.assertEqual(list(st), ["A - Steady"])
        self.assertEqual(len(labels), 12)


if __name__ == "__main__":
    unittest.main()
