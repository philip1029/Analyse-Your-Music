"""analysis.artist_merge (같은 사람의 다른 이름 직접 합치기) 테스트. 합성 데이터만 쓴다. 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import csv

from app.analysis.artist_merge import add_rule, load_rules, preview, restorable_rows, restore_rules, undo_merge  # noqa: E402


def frame():
    rows = []

    def add(n, artist, source, track="Song", start=0):
        for i in range(n):
            rows.append({"uts": 1000 + start + i, "artist": artist, "track": f"{track}{i}", "source": source})

    add(4, "검정치마", "L")
    add(70, "검정치마", "A", start=100)
    add(58, "The Black Skirts", "A", start=500)
    add(3, "Other", "L", start=900)
    return pd.DataFrame(rows)


class PreviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "artist_merge.txt"

    def tearDown(self):
        self.tmp.cleanup()

    def test_counts_and_direction_follow_lastfm(self):
        p = preview(frame(), "The Black Skirts", "검정치마", self.path)
        self.assertIsNone(p["error"])
        self.assertEqual((p["variant"]["A"], p["variant"]["L"]), (58, 0))
        self.assertEqual((p["canonical"]["A"], p["canonical"]["L"]), (70, 4))
        self.assertFalse(p["suggest_swap"])
        # 방향이 거꾸로면(L 행이 있는 쪽이 변형) 바꾸라고 권한다
        self.assertTrue(preview(frame(), "검정치마", "The Black Skirts", self.path)["suggest_swap"])

    def test_errors(self):
        df = frame()
        self.assertIn("서로 다른", preview(df, "Other", "Other", self.path)["error"])
        self.assertIn("기록에 없는", preview(df, "Nobody", "Other", self.path)["error"])
        self.assertIn("두 명", preview(df, "", "Other", self.path)["error"])

    def test_collision_blocks_merge(self):
        df = frame()
        dup = df[df["artist"] == "검정치마"].head(1).assign(artist="The Black Skirts")   # 같은 uts·곡이 양쪽에 있음
        p = preview(pd.concat([df, dup]), "The Black Skirts", "검정치마", self.path)
        self.assertEqual(p["collisions"], 1)
        self.assertIn("겹쳐서", p["error"])

    def test_existing_rule_blocks_chain(self):
        add_rule(self.path, "The Black Skirts", "검정치마")
        self.assertIn("이미", preview(frame(), "The Black Skirts", "Other", self.path)["error"])
        self.assertIn("통일 이름이 될 수 없어요", preview(frame(), "Other", "The Black Skirts", self.path)["error"])


class RulesFileTest(unittest.TestCase):
    def test_add_and_restore(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "artist_merge.txt"
            before = add_rule(path, " A ", " B ")
            self.assertIsNone(before)
            self.assertEqual(load_rules(path), {"A": "B"})
            before2 = add_rule(path, "C", "D")
            self.assertEqual(load_rules(path), {"A": "B", "C": "D"})
            restore_rules(path, before2)
            self.assertEqual(load_rules(path), {"A": "B"})
            restore_rules(path, before)
            self.assertFalse(path.exists())

    def test_load_ignores_comments_and_bad_lines(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "m.txt"
            path.write_text("# 주석\n\nA -> B\nbad line\nX -> X\n", encoding="utf-8")
            self.assertEqual(load_rules(path), {"A": "B"})


class UndoTest(unittest.TestCase):
    HEADER = ["uts", "utc_time", "artist", "album", "track", "source"]

    def setup_files(self, d: Path):
        """합친 뒤의 상태: 변형 이름 행 2개가 통일 이름으로 바뀌어 있고, 합칠 때의 변경 기록이 있다."""
        data = [
            {"uts": "1", "utc_time": "t1", "artist": "검정치마", "album": "a", "track": "x", "source": "L"},
            {"uts": "2", "utc_time": "t2", "artist": "검정치마", "album": "a", "track": "y", "source": "A"},   # 원래 The Black Skirts
            {"uts": "3", "utc_time": "t3", "artist": "검정치마", "album": "a", "track": "z", "source": "A"},   # 원래 The Black Skirts
        ]
        with open(d / "me_scrobbles.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=self.HEADER)
            w.writeheader()
            w.writerows(data)
        log = [{"uts": str(u), "utc_time": f"t{u}", "track": t, "source": "A", "old_artist": "The Black Skirts", "new_artist": "검정치마", "rule": "manual_merge", "changed_at": "now"} for u, t in ((2, "y"), (3, "z"))]
        with open(d / "artist_normalize_log.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(log[0]))
            w.writeheader()
            w.writerows(log)
        rules, canon = d / "artist_merge.txt", d / "artist_canonical.txt"
        rules.write_text("# 주석\nThe Black Skirts -> 검정치마\nParannoul -> 파란노을\n", encoding="utf-8")
        canon.write_text("# 목록\nThe Black Skirts -> 검정치마\n", encoding="utf-8")
        return rules, canon

    def test_undo_restores_only_merged_rows_and_removes_rule(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            rules, canon = self.setup_files(d)
            df = pd.DataFrame([{"uts": u, "artist": a, "track": tr, "source": s} for u, a, tr, s in (("1", "검정치마", "x", "L"), ("2", "검정치마", "y", "A"), ("3", "검정치마", "z", "A"))])
            self.assertEqual(restorable_rows(df, d, "The Black Skirts", "검정치마"), 2)
            r = undo_merge(d, rules, canon, "The Black Skirts", "검정치마")
            self.assertEqual(r["restored_rows"], 2)
            self.assertTrue((d / r["backup"]).exists())
            with open(d / "me_scrobbles.csv", newline="", encoding="utf-8-sig") as f:
                out = {x["uts"]: x["artist"] for x in csv.DictReader(f)}
            self.assertEqual(out, {"1": "검정치마", "2": "The Black Skirts", "3": "The Black Skirts"})   # L 행은 그대로
            self.assertEqual(load_rules(rules), {"Parannoul": "파란노을"})                          # 다른 규칙은 남는다
            self.assertNotIn("The Black Skirts", canon.read_text(encoding="utf-8"))
            self.assertIn("# 주석", rules.read_text(encoding="utf-8"))
            # 되돌린 기록이 로그에 남아서 두 번 되돌릴 수는 없다
            with open(d / "artist_normalize_log.csv", newline="", encoding="utf-8-sig") as f:
                log = list(csv.DictReader(f))
            self.assertEqual([x["rule"] for x in log].count("undo_merge"), 2)
            with self.assertRaises(ValueError):
                undo_merge(d, rules, canon, "The Black Skirts", "검정치마")

    def test_undo_unknown_rule_raises(self):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            rules, canon = self.setup_files(d)
            with self.assertRaises(ValueError):
                undo_merge(d, rules, canon, "Nobody", "검정치마")


if __name__ == "__main__":
    unittest.main()
