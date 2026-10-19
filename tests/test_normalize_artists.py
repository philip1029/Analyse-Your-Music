"""normalize_artists.build_mapping 규칙 테스트 (합성 데이터). 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import normalize_artists as na  # noqa: E402


def S(a=0, l=0):
    return {"A": a, "L": l}


class BuildMappingTest(unittest.TestCase):
    def test_case_only_variant_maps_to_lastfm_spelling(self):
        m, groups, _ = na.build_mapping({"Have A Nice Life": S(a=416), "Have a Nice Life": S(a=3, l=168)})
        self.assertEqual(m, {"Have A Nice Life": "Have a Nice Life"})
        self.assertEqual(groups, [("Have a Nice Life", ["Have A Nice Life"])])

    def test_canonical_is_the_most_used_lastfm_spelling(self):
        stats = {"涼宮ハルヒ(CV.平野綾)": S(a=26), "涼宮ハルヒ(cv.平野綾)": S(l=12), "涼宮ハルヒ (CV.平野 綾)": S(l=2)}
        m, _, _ = na.build_mapping(stats)
        self.assertEqual(set(m.values()), {"涼宮ハルヒ(cv.平野綾)"})
        self.assertEqual(len(m), 2)

    def test_tie_between_lastfm_spellings_uses_total_rows_then_name(self):
        m, _, _ = na.build_mapping({"Angine de Poitrine": S(a=2, l=2), "Angine de poitrine": S(l=2)})
        self.assertEqual(m, {"Angine de poitrine": "Angine de Poitrine"})

    def test_group_without_lastfm_rows_is_left_alone(self):
        m, groups, skipped = na.build_mapping({"Foo Bar": S(a=3), "foo bar": S(a=1)})
        self.assertEqual((m, groups), ({}, []))
        self.assertEqual(skipped, [["Foo Bar", "foo bar"]])

    def test_keep_separate_names_are_not_merged_or_used(self):
        stats = {"LIA & VISUAL ARTS / Key": S(l=95), "Lia & VISUAL ARTS / Key": S(a=151)}
        m, groups, _ = na.build_mapping(stats, {"LIA & VISUAL ARTS / Key", "Lia & VISUAL ARTS / Key"})
        self.assertEqual((m, groups), ({}, []))

    def test_without_keep_separate_those_two_would_merge(self):
        stats = {"LIA & VISUAL ARTS / Key": S(l=95), "Lia & VISUAL ARTS / Key": S(a=151)}
        m, _, _ = na.build_mapping(stats)
        self.assertEqual(m, {"Lia & VISUAL ARTS / Key": "LIA & VISUAL ARTS / Key"})   # 그래서 예외 목록이 필요

    def test_feat_credit_and_different_punctuation_are_not_merged(self):
        stats = {"OutKast": S(a=187, l=1), "Outkast featuring Slimm Calhoun & C-Bone": S(a=1),
                 "Kendrick Lamar & SZA": S(l=1), "Kendrick Lamar, SZA": S(a=1)}
        m, _, _ = na.build_mapping(stats)
        self.assertEqual(m, {})

    def test_different_people_with_a_common_prefix_are_not_merged(self):
        m, _, _ = na.build_mapping({"Lia Ouyang Rusli": S(a=13), "Lia": S(l=3)})
        self.assertEqual(m, {})

    def test_empty_names_are_ignored(self):
        m, _, _ = na.build_mapping({"": S(a=5), "X": S(l=1)})
        self.assertEqual(m, {})

    def test_load_keep_separate_ignores_comments_and_blank_lines(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "keep.txt"
            p.write_text("# 주석\n\nAAA & BBB\n  CCC  \n", encoding="utf-8")
            self.assertEqual(na.load_keep_separate(p), {"AAA & BBB", "CCC"})
            self.assertEqual(na.load_keep_separate(Path(d) / "missing.txt"), set())


if __name__ == "__main__":
    unittest.main()
