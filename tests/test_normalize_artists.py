"""normalize_artists.build_mapping 규칙 테스트 (합성 데이터). 실행:
    python3 -m unittest discover -s tests -v
"""

import contextlib
import csv
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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


class ManualMergeTest(unittest.TestCase):
    def test_manual_merge_maps_variant_to_given_name(self):
        stats = {"Parannoul": S(a=592), "파란노을": S(a=193, l=140)}
        m, groups = {}, []
        applied = na.apply_manual_merges(m, groups, stats, {"Parannoul": "파란노을"})
        self.assertEqual((m, applied), ({"Parannoul": "파란노을"}, {"Parannoul"}))
        self.assertEqual(groups, [("파란노을", ["Parannoul"])])

    def test_manual_merge_needs_both_names_in_data(self):
        for stats in ({"Parannoul": S(a=5)}, {"파란노을": S(l=5)}):
            m = {}
            self.assertEqual(na.apply_manual_merges(m, [], stats, {"Parannoul": "파란노을"}), set())
            self.assertEqual(m, {})

    def test_new_name_is_applied_only_when_explicitly_allowed(self):
        # 이름 바꾸기: 통일 이름이 데이터에 없어도, 이번 실행에서 허용한 새 이름이면 규칙이 먹는다
        stats = {"THORNAPPLE": S(a=133)}
        m, groups = {}, []
        self.assertEqual(na.apply_manual_merges(m, groups, stats, {"THORNAPPLE": "쏜애플"}), set())          # 평소에는 오타 방지로 무시
        self.assertEqual(m, {})
        applied = na.apply_manual_merges(m, groups, stats, {"THORNAPPLE": "쏜애플"}, allow_new={"쏜애플"})
        self.assertEqual((m, applied), ({"THORNAPPLE": "쏜애플"}, {"THORNAPPLE"}))
        self.assertEqual(groups, [("쏜애플", ["THORNAPPLE"])])
        # 허용한 이름이어도 바꿀 이름(변형)이 데이터에 없으면 아무것도 하지 않는다
        m2 = {}
        self.assertEqual(na.apply_manual_merges(m2, [], {"Other": S(a=1)}, {"THORNAPPLE": "쏜애플"}, allow_new={"쏜애플"}), set())
        self.assertEqual(m2, {})
        # 허용 목록에 없는 다른 새 이름 규칙은 여전히 무시된다
        m3 = {}
        self.assertEqual(na.apply_manual_merges(m3, [], stats, {"THORNAPPLE": "엉뚱한 이름"}, allow_new={"쏜애플"}), set())

    def test_manual_merge_follows_automatic_rename_of_target(self):
        stats = {"X": S(a=1), "Foo Bar": S(a=1), "foo bar": S(l=3)}
        m, _, _ = na.build_mapping(stats)
        self.assertEqual(m, {"Foo Bar": "foo bar"})
        na.apply_manual_merges(m, [], stats, {"X": "Foo Bar"})
        self.assertEqual(m["X"], "foo bar")

    def test_load_manual_merges_parses_arrows_and_ignores_comments(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "merge.txt"
            p.write_text("# 주석\n\nA -> B\n bad line\nC->D\nE -> E\n", encoding="utf-8")
            self.assertEqual(na.load_manual_merges(p), {"A": "B", "C": "D"})
            self.assertEqual(na.load_manual_merges(Path(d) / "none.txt"), {})


class RenameEndToEndTest(unittest.TestCase):
    """실제 CSV 로 끝까지: 새 이름으로 바꾸고, 그 뒤 들어온 같은 이름의 새 기록도 규칙으로 따라 바뀐다."""

    HEADER = ["uts", "utc_time", "artist", "album", "track", "source"]

    def write_rows(self, path, rows):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=self.HEADER)
            w.writeheader()
            for u, artist, source in rows:
                w.writerow({"uts": u, "utc_time": f"t{u}", "artist": artist, "album": "a", "track": f"song{u}", "source": source})

    def read_artists(self, path):
        with open(path, newline="", encoding="utf-8-sig") as f:
            return {r["uts"]: r["artist"] for r in csv.DictReader(f)}

    def run_script(self, d, *extra):
        argv = ["normalize_artists.py", "--data-dir", str(d), "--keep-separate", str(d / "none.txt"), "--manual-merge", str(d / "artist_merge.txt"), "--apply", "--json", *extra]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(na, "CANONICAL_FILE", d / "artist_canonical.txt"), contextlib.redirect_stdout(io.StringIO()):
            na.main()

    def test_rename_to_new_name_then_new_scrobbles_follow_the_rule(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            csv_path = d / "me_scrobbles.csv"
            self.write_rows(csv_path, [("1", "THORNAPPLE", "A"), ("2", "THORNAPPLE", "A"), ("3", "Other", "L")])
            (d / "artist_merge.txt").write_text("THORNAPPLE -> 쏜애플\n", encoding="utf-8")

            self.run_script(d)                                           # 허용 없이는 새 이름 규칙이 무시된다
            self.assertEqual(set(self.read_artists(csv_path).values()), {"THORNAPPLE", "Other"})

            self.run_script(d, "--allow-new", "쏜애플")                  # 이름 바꾸기: 허용한 새 이름
            self.assertEqual(self.read_artists(csv_path), {"1": "쏜애플", "2": "쏜애플", "3": "Other"})
            self.assertTrue(list(d.glob("*.bak_artistnorm_*")))          # 백업이 남는다
            with open(d / "artist_normalize_log.csv", newline="", encoding="utf-8-sig") as f:
                log = list(csv.DictReader(f))
            self.assertEqual([(r["old_artist"], r["new_artist"], r["rule"]) for r in log], [("THORNAPPLE", "쏜애플", "manual_merge")] * 2)

            # 새로고침으로 같은 옛 이름의 새 기록이 들어와도, 이제 새 이름이 기록에 있으므로 허용 없이 규칙대로 바뀐다
            self.write_rows(csv_path, [("1", "쏜애플", "A"), ("2", "쏜애플", "A"), ("3", "Other", "L"), ("4", "THORNAPPLE", "L")])
            self.run_script(d)
            self.assertEqual(self.read_artists(csv_path)["4"], "쏜애플")


if __name__ == "__main__":
    unittest.main()
