"""normalize_titles.build_title_mapping 규칙 테스트 (합성 데이터). 실행:
    python3 -m unittest discover -s tests -v
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import normalize_titles as nt  # noqa: E402


def R(artist, title, source, n=1, field="track"):
    return [{"artist": artist, "source": source, field: title, "album": "", "track": "", **({field: title})} for _ in range(n)]


class BuildTitleMappingTest(unittest.TestCase):
    def test_apple_spelling_maps_to_lastfm_spelling(self):
        rows = R("Pink Floyd", "Shine On You Crazy Diamond", "A", 101) + R("Pink Floyd", "Shine on You Crazy Diamond", "L", 15)
        m, groups, _ = nt.build_title_mapping(rows, "track")
        self.assertEqual(m, {("Pink Floyd", "Shine On You Crazy Diamond"): "Shine on You Crazy Diamond"})
        self.assertEqual(groups, [("Pink Floyd", "Shine on You Crazy Diamond", ["Shine On You Crazy Diamond"])])

    def test_canonical_is_most_used_lastfm_spelling_even_if_apple_has_more_rows(self):
        rows = R("X", "Foo Bar", "A", 50) + R("X", "foo bar", "L", 2) + R("X", "Foo bar", "L", 3)
        m, _, _ = nt.build_title_mapping(rows, "track")
        self.assertEqual(set(m.values()), {"Foo bar"})
        self.assertEqual(len(m), 2)

    def test_same_title_under_different_artists_is_not_merged(self):
        rows = R("Melvins", "Untitled", "L", 2) + R("Radiohead", "untitled", "A", 3)
        self.assertEqual(nt.build_title_mapping(rows, "track")[0], {})

    def test_group_without_lastfm_rows_is_left_alone(self):
        m, groups, skipped = nt.build_title_mapping(R("X", "Foo", "A", 2) + R("X", "foo", "A", 1), "track")
        self.assertEqual((m, groups), ({}, []))
        self.assertEqual(skipped, [("X", ["Foo", "foo"])])

    def test_different_punctuation_or_suffix_is_not_merged(self):
        rows = R("X", "Intro", "L") + R("X", "Intro (Live)", "A") + R("X", "Rock & Roll", "L") + R("X", "Rock and Roll", "A")
        self.assertEqual(nt.build_title_mapping(rows, "track")[0], {})

    def test_nfkc_forms_such_as_ellipsis_char_are_treated_as_the_same_title(self):
        rows = R("X", "Antennas...", "L") + R("X", "Antennas…", "A")
        self.assertEqual(nt.build_title_mapping(rows, "track")[0], {("X", "Antennas…"): "Antennas..."})

    def test_spaces_are_ignored_and_empty_titles_skipped(self):
        rows = R("X", "Pts. 1-5", "L") + R("X", "Pts.  1-5", "A") + R("X", "", "L")
        m, _, _ = nt.build_title_mapping(rows, "track")
        self.assertEqual(m, {("X", "Pts.  1-5"): "Pts. 1-5"})

    def test_album_field_uses_the_same_rule(self):
        rows = R("my bloody valentine", "loveless", "A", 419, "album") + R("my bloody valentine", "Loveless", "L", 72, "album")
        m, _, _ = nt.build_title_mapping(rows, "album")
        self.assertEqual(m, {("my bloody valentine", "loveless"): "Loveless"})


SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "normalize_titles.py"
CSV_HEADER = "uts,utc_time,artist,album,track,source\n"


class CliTest(unittest.TestCase):
    """최신 스크롭 불러오기 버튼이 부르는 형태(--apply --json)를 임시 data 폴더로 확인한다."""

    def run_cli(self, d, *flags):
        out = subprocess.run([sys.executable, str(SCRIPT), "--data-dir", d, *flags], capture_output=True, text=True, timeout=60)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def test_apply_json_changes_rows_with_backup_and_log(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = Path(d) / "u_scrobbles.csv"
            csv_path.write_text(CSV_HEADER + "2,2026-01-02 00:00:00,PF,WYWH,Have A Cigar,A\n1,2026-01-01 00:00:00,PF,WYWH,Have a Cigar,L\n", encoding="utf-8")
            res = json.loads(self.run_cli(d, "--apply", "--json").strip().splitlines()[-1])
            self.assertEqual((res["applied"], res["tracks"], res["albums"]), (True, 1, 0))
            self.assertIn("Have a Cigar", csv_path.read_text(encoding="utf-8"))
            self.assertNotIn("Have A Cigar", csv_path.read_text(encoding="utf-8"))
            self.assertTrue(list(Path(d).glob("*.bak_titlenorm_*")))
            self.assertTrue((Path(d) / "title_normalize_log.csv").exists())

    def test_apply_with_nothing_to_change_writes_no_backup(self):
        with tempfile.TemporaryDirectory() as d:
            csv_path = Path(d) / "u_scrobbles.csv"
            csv_path.write_text(CSV_HEADER + "1,2026-01-01 00:00:00,PF,WYWH,Have a Cigar,L\n", encoding="utf-8")
            before = csv_path.read_bytes()
            res = json.loads(self.run_cli(d, "--apply", "--json").strip().splitlines()[-1])
            self.assertEqual((res["applied"], res["backup"]), (False, None))
            self.assertEqual(csv_path.read_bytes(), before)
            self.assertEqual(list(Path(d).glob("*.bak_*")), [])
            self.assertFalse((Path(d) / "title_normalize_log.csv").exists())


if __name__ == "__main__":
    unittest.main()
