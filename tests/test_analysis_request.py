"""프롬프트 끝 "분석 요청" 블록(원칙 + A~E 구조) 테스트. 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis.ai_prompt import analysis_request  # noqa: E402


class AnalysisRequestTest(unittest.TestCase):
    def text(self, kind, label="2025년", prev="2024년"):
        return "\n".join(analysis_request(kind, label, prev))

    def test_same_structure_for_every_kind(self):
        for kind in ("all", "month", "year", "week"):
            t = self.text(kind)
            self.assertTrue(t.startswith("## 분석 요청"), kind)
            for marker in ("[원칙]", "[요청]", "A.", "B.", "C.", "D.", "E.", "A~E 순서", "관찰(수치) / 해석 / 다른 해석 가능성", "불확실"):
                self.assertIn(marker, t, f"{kind}: {marker}")
            self.assertLess(t.index("A."), t.index("B."))
            self.assertLess(t.index("D."), t.index("E."))

    def test_no_length_limit(self):
        for kind in ("all", "month", "year", "week"):
            t = self.text(kind)
            self.assertNotIn("1,500", t)
            self.assertNotIn("이내로 써", t)

    def test_period_kinds_mention_labels_and_all_does_not_need_them(self):
        self.assertIn("2025년", self.text("year"))
        self.assertIn("2024년과 달라진", self.text("year"))
        self.assertNotIn("2024년", self.text("all"))            # 기간 전체는 비교 기간이 없다

    def test_recommendation_count_by_kind(self):
        self.assertIn("3~5명", self.text("month"))
        self.assertIn("5명 추천", self.text("year"))
        self.assertIn("2~3명", self.text("week"))

    def test_only_cites_sections_that_exist(self):
        # 이 프롬프트에 없는 지표(신뢰도 블록, 이동 지수, 정착률 등)를 참조하면 AI 가 수치를 지어낸다
        for kind in ("all", "month", "year", "week"):
            t = self.text(kind)
            for ghost in ("신뢰도 블록", "이동 지수", "정착률", "코어 아티스트", "앨범 연속성"):
                self.assertNotIn(ghost, t)


if __name__ == "__main__":
    unittest.main()
