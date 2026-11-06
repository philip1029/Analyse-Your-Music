"""analysis.recommend (오늘의 추천 앨범) 테스트. 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis import recommend  # noqa: E402


def frame():
    rows = []

    def add(artist, album, n_tracks, days, plays_per_track=1):
        """days: 들은 날짜 목록. 그날마다 모든 곡을 plays_per_track 번 듣는다."""
        for d in days:
            for t in range(n_tracks):
                for _ in range(plays_per_track):
                    rows.append({"utc_time": f"{d} 03:00:00", "artist": artist, "album": album, "track": f"{album} t{t}"})

    add("Old Fav", "Dormant LP", 10, [f"2024-01-{d:02d}" for d in (1, 2, 3, 4)])               # 40회, 4일, 아주 오래전
    add("Old Fav", "Dormant Single - Single", 1, ["2024-01-01"] * 1)                           # 너무 적게 들음
    add("Fresh", "Recent LP", 10, [f"2026-10-{d:02d}" for d in (1, 2, 3, 4)])                  # 최근이라 뜸하지 않음
    add("Once Artist", "Heard Once", 8, ["2025-01-10"])                                        # 하루만, 8회
    add("Once Artist", "One Track Only", 1, ["2025-01-11"])                                    # 한 곡만 (once_min_plays 미달)
    add("Once Artist", "Heard Once - Single", 3, ["2025-01-12"])                               # 싱글은 제외
    add("Big Artist", "Main LP", 10, [f"2026-0{m}-0{d}" for m in (1, 2, 3) for d in (1, 2, 3, 4)], 2)   # 240회, 주력
    add("Big Artist", "Side LP", 2, ["2026-10-31"])                                            # 2회 (주력의 1% 미만) -> 도전
    add("Big Artist", "Half LP", 10, [f"2026-04-0{d}" for d in (1, 2, 3)], 3)                  # 90회 -> 도전 아님(비율 초과)
    return pd.DataFrame(rows)


class RecommendTest(unittest.TestCase):
    def setUp(self):
        self.df = frame()
        self.cfg = dict(recommend.DEFAULTS)

    def cats(self, **kw):
        res = recommend.build_recommendations(self.df, today="2026-11-06", cfg={**self.cfg, **kw})
        return {c["id"]: c for c in res["categories"]}

    def names(self, cat):
        return {p["name"] for p in cat["picks"]}

    def test_dormant_rules(self):
        names = self.names(self.cats(per_category=10, pool=10)["dormant"])
        self.assertEqual(names, {"Dormant LP", "Main LP", "Half LP"})        # 최근 앨범·적게 들은 앨범은 제외

    def test_once_rules(self):
        cats = self.cats()
        names = self.names(cats["once"])
        self.assertIn("Heard Once", names)
        self.assertNotIn("One Track Only", names)                            # 한 곡만
        self.assertNotIn("Heard Once - Single", names)                       # 싱글
        self.assertEqual(self.names(self.cats(exclude_singles=0)["once"]) >= {"Heard Once - Single"}, True)

    def test_challenge_rules(self):
        names = self.names(self.cats()["challenge"])
        self.assertIn("Side LP", names)
        self.assertNotIn("Half LP", names)                                   # 주력 앨범의 20% 넘음
        self.assertNotIn("Main LP", names)

    def test_album_appears_in_one_category_only(self):
        cats = self.cats(per_category=5)
        seen = [p["name"] for c in cats.values() for p in c["picks"]]
        self.assertEqual(len(seen), len(set(seen)))

    def test_deterministic_and_salt_changes_pick_order(self):
        a = recommend.build_recommendations(self.df, today="2026-11-06", cfg={**self.cfg, "per_category": 1, "pool": 5})
        b = recommend.build_recommendations(self.df, today="2026-11-06", cfg={**self.cfg, "per_category": 1, "pool": 5})
        self.assertEqual(a, b)
        picks = {tuple(p["name"] for c in recommend.build_recommendations(self.df, today="2026-11-06", salt=s, cfg={**self.cfg, "per_category": 1, "pool": 5})["categories"] for p in c["picks"]) for s in range(12)}
        self.assertGreater(len(picks), 1)

    def test_reason_and_numbers(self):
        p = next(p for p in self.cats(per_category=10, pool=10)["dormant"]["picks"] if p["name"] == "Dormant LP")
        self.assertEqual((p["plays"], p["days"], p["tracks"]), (40, 4, 10))
        self.assertIn("40번", p["reason"])
        self.assertGreater(p["days_since"], 150)

    def test_empty_frame(self):
        res = recommend.build_recommendations(self.df.iloc[0:0], today="2026-11-06")
        self.assertTrue(all(c["picks"] == [] for c in res["categories"]))

    def test_load_config_overrides_and_ignores_bad_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "r.txt"
            path.write_text("# c\ndormant_days = 30   # 짧게\nonce_min_plays = abc\nunknown = 5\nper_category = -1\npool=20\n", encoding="utf-8")
            cfg = recommend.load_config(path)
        self.assertEqual(cfg["dormant_days"], 30)
        self.assertEqual(cfg["once_min_plays"], recommend.DEFAULTS["once_min_plays"])
        self.assertEqual(cfg["per_category"], recommend.DEFAULTS["per_category"])
        self.assertEqual(cfg["pool"], 20)
        self.assertEqual(recommend.load_config(Path("/nonexistent/x.txt")), recommend.DEFAULTS)


if __name__ == "__main__":
    unittest.main()
