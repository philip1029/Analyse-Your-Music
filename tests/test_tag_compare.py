"""장르/태그 분포 비교(두 기간을 같은 축에서 겹쳐 보기) 테스트. 합성 캐시 디렉터리를 쓴다. 실행:
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

from app.analysis import taste  # noqa: E402


def plays(**counts):
    return pd.DataFrame([{"artist": a} for a, n in counts.items() for _ in range(n)])


class TagCompareTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        cache = Path(self.tmp.name)
        for name, tags in {
            "Rocker": [("rock", 100), ("pop", 50)],
            "Jazzer": [("jazz", 100)],
            "Mixed": [("Rock", 40), ("jazz", 20)],              # 대소문자는 합쳐서 센다
        }.items():
            (cache / f"{taste._slugify(name)}.json").write_text(json.dumps([{"name": t, "count": c} for t, c in tags]), encoding="utf-8")
        self.patches = [mock.patch.object(taste, "CACHE_DIR", cache), mock.patch.object(taste, "resolve_artist_name", side_effect=lambda n: n)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_scores_total_and_coverage(self):
        r = taste.compute_tag_scores(plays(Rocker=3, Jazzer=1, Unknown=5))
        self.assertEqual(r["scores"], {"rock": 3.0, "pop": 1.5, "jazz": 1.0})
        self.assertAlmostEqual(r["total_score"], 5.5)
        self.assertEqual((r["covered_artists"], r["total_artists"], r["covered_plays"], r["total_plays"]), (2, 3, 4, 9))

    def test_distribution_is_unchanged(self):
        r = taste.compute_tag_distribution(plays(Rocker=3, Jazzer=1))
        self.assertEqual(r["tags"], [{"tag": "rock", "score": 3.0}, {"tag": "pop", "score": 1.5}, {"tag": "jazz", "score": 1.0}])
        self.assertEqual(set(r), {"tags", "covered_artists", "total_artists", "covered_plays", "total_plays"})

    def test_comparison_uses_shares_so_different_sizes_are_comparable(self):
        base = plays(Rocker=300, Jazzer=100)                      # 큰 기간
        month = plays(Jazzer=4)                                    # 작은 기간
        r = taste.compute_tag_comparison(base, month)
        by = {t["tag"]: t for t in r["tags"]}
        self.assertEqual(by["rock"]["base"], 54.55)
        self.assertEqual(by["rock"]["compare"], 0.0)
        self.assertEqual(by["jazz"]["compare"], 100.0)
        self.assertEqual(by["jazz"]["base"], 18.18)
        self.assertAlmostEqual(sum(t["base"] for t in r["tags"]), 100, delta=0.1)
        self.assertEqual(r["tags"][0]["tag"], "jazz")                # 더 큰 쪽 비율(100%) 순
        self.assertEqual(r["compare"]["total_plays"], 4)

    def test_union_of_each_periods_top_tags_and_cap(self):
        base, month = plays(Rocker=10), plays(Jazzer=10)
        r = taste.compute_tag_comparison(base, month, top_n=1)
        self.assertEqual({t["tag"] for t in r["tags"]}, {"rock", "jazz"})          # 각 기간의 1등이 모두 들어간다
        self.assertEqual(len(taste.compute_tag_comparison(base, month, top_n=5, max_tags=2)["tags"]), 2)

    def test_empty_period_gives_zero_shares_not_an_error(self):
        r = taste.compute_tag_comparison(plays(Rocker=2), plays(Nobody=3))
        self.assertTrue(all(t["compare"] == 0.0 for t in r["tags"]))
        self.assertEqual(r["compare"], {"covered_artists": 0, "total_artists": 1, "covered_plays": 0, "total_plays": 3})
        empty = taste.compute_tag_comparison(pd.DataFrame({"artist": []}), pd.DataFrame({"artist": []}))
        self.assertEqual(empty["tags"], [])


if __name__ == "__main__":
    unittest.main()
