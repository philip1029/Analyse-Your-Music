"""기간별(주·월·연) AI 프롬프트 생성 회귀 테스트: 메타의 label 이 문자열이고, 본문에 함수 표현이 새지 않는다.
(청취 시간 표를 넣을 때 지역 변수 label 을 함수로 덮어써서 메타에 "[object Object]"가 나왔던 문제)

    python3 -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis import ai_prompt, ai_prompt_period as app_  # noqa: E402
from app.analysis import listening_time as lt  # noqa: E402
from app.analysis import library as lib  # noqa: E402
from app.lastfm import durations as d  # noqa: E402


def frame():
    rows = []
    for day in range(1, 29):
        for month in (1, 2, 3):
            for i in range(3):
                rows.append({
                    "utc_time": f"2025-{month:02d}-{day:02d} {10 + i:02d}:00:00",
                    "artist": ["A", "B", "C"][i], "album": f"Album {i}", "track": f"Song {i}", "source": "L",
                })
    return pd.DataFrame(rows)


class PeriodPromptTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / d.CACHE_NAME
        d.save_cache(path, {d.cache_key("A", "Song 0"): {"sec": 200, "src": "apple", "tried": 1}})
        lookup = d.DurationLookup(path)
        self.patches = [mock.patch.object(lt, "durations", lookup), mock.patch.object(lib, "durations", lookup)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_period_prompts_have_string_labels_and_no_function_text(self):
        df = frame()
        for period in ("week", "month", "year"):
            periods = app_.list_periods(df, period)
            res = app_.build_period_prompt(df, period, periods[0]["key"])
            self.assertIsInstance(res["meta"]["label"], str, period)
            self.assertNotIn("<function", res["prompt"], period)
            self.assertNotIn("<lambda", res["prompt"], period)
            self.assertIn("총 청취 시간", res["prompt"], period)
            self.assertIn("청취 시간 기준 Top 5", res["prompt"], period)

    def test_all_time_prompt_has_time_sections_without_function_text(self):
        text = ai_prompt.build_ai_prompt(frame())
        self.assertIn("총 청취 시간(추정)", text)
        self.assertIn("청취 시간 기준 순위", text)
        self.assertNotIn("<function", text)
        self.assertNotIn("<lambda", text)


if __name__ == "__main__":
    unittest.main()
