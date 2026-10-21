"""analysis.title_merge (같은 앨범/곡의 다른 제목 직접 합치기) 테스트. 합성 데이터만 쓴다. 실행:
    python3 -m unittest discover -s tests -v
"""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from app.analysis.title_merge import add_rule, load_rules, preview, restorable_rows, restore_rules, titles_of, undo_merge  # noqa: E402
from normalize_titles import apply_manual_title_merges, build_title_mapping, load_manual_title_merges  # noqa: E402

HEADER = ["uts", "utc_time", "artist", "album", "track", "source"]


def rows():
    out = []
    n = [0]

    def add(count, artist, album, track, source):
        for _ in range(count):
            n[0] += 1
            out.append({"uts": str(1000 + n[0]), "utc_time": f"t{n[0]}", "artist": artist, "album": album, "track": track, "source": source})

    add(5, "김사월", "Romance", "Kiss", "A")
    add(3, "김사월", "로맨스", "키스", "L")
    add(2, "김사월", "로맨스", "죽어", "L")
    add(4, "Other", "Romance", "Kiss", "A")
    return out


class TitlesAndPreviewTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rules = Path(self.tmp.name) / "title_merge.txt"
        self.df = pd.DataFrame(rows())

    def tearDown(self):
        self.tmp.cleanup()

    def test_titles_of_counts_sources_within_artist(self):
        t = {x["title"]: x for x in titles_of(self.df, "김사월", "album")}
        self.assertEqual((t["Romance"]["A"], t["Romance"]["L"]), (5, 0))
        self.assertEqual((t["로맨스"]["A"], t["로맨스"]["L"]), (0, 5))

    def test_preview_prefers_lastfm_spelling(self):
        p = preview(self.df, "album", "김사월", "로맨스", "Romance", self.rules)
        self.assertIsNone(p["error"])
        self.assertTrue(p["suggest_swap"])                 # 변형(로맨스) 쪽에 L 행이 많다 → 뒤집으라고 권한다
        self.assertFalse(preview(self.df, "album", "김사월", "Romance", "로맨스", self.rules)["suggest_swap"])

    def test_preview_errors(self):
        self.assertIn("없는", preview(self.df, "album", "김사월", "Nope", "로맨스", self.rules)["error"])
        self.assertIn("서로 다른", preview(self.df, "album", "김사월", "로맨스", "로맨스", self.rules)["error"])

    def test_track_collision(self):
        df = pd.concat([self.df, pd.DataFrame([{**rows()[0], "track": "키스"}])])      # 같은 uts 가 양쪽 곡명에 있음
        p = preview(df, "track", "김사월", "Kiss", "키스", self.rules)
        self.assertEqual(p["collisions"], 1)
        self.assertIn("겹쳐서", p["error"])


class ScriptRulesTest(unittest.TestCase):
    def test_manual_rule_maps_only_that_artist_and_prefers_final_spelling(self):
        with tempfile.TemporaryDirectory() as d:
            rules = Path(d) / "title_merge.txt"
            add_rule(rules, "album", "김사월", "Romance", "로맨스")
            data = rows()
            maps = {f: build_title_mapping(data, f)[0] for f in ("track", "album")}
            groups = {f: [] for f in ("track", "album")}
            applied = apply_manual_title_merges(data, maps, groups, load_manual_title_merges(rules))
            self.assertEqual(maps["album"], {("김사월", "Romance"): "로맨스"})        # Other 의 Romance 는 그대로
            self.assertEqual(applied["album"], {("김사월", "Romance")})
            self.assertEqual(maps["track"], {})

    def test_rule_ignored_when_variant_absent(self):
        with tempfile.TemporaryDirectory() as d:
            rules = Path(d) / "title_merge.txt"
            add_rule(rules, "track", "김사월", "Nope", "키스")
            data = rows()
            maps = {f: {} for f in ("track", "album")}
            applied = apply_manual_title_merges(data, maps, {f: [] for f in maps}, load_manual_title_merges(rules))
            self.assertEqual((maps["track"], applied["track"]), ({}, set()))

    def test_rules_file_roundtrip_and_restore(self):
        with tempfile.TemporaryDirectory() as d:
            rules = Path(d) / "title_merge.txt"
            before = add_rule(rules, "track", "A", "x", "y")
            self.assertEqual(load_rules(rules), [{"kind": "track", "artist": "A", "variant": "x", "canonical": "y"}])
            restore_rules(rules, before)
            self.assertFalse(rules.exists())


class UndoTest(unittest.TestCase):
    def write_state(self, d: Path, kind: str):
        """합친 뒤 상태: 김사월의 Romance 5행이 로맨스(앨범) 또는 Kiss 5행이 키스(곡)로 바뀌어 있다."""
        data = rows()
        log = []
        for r in data:
            if r["artist"] == "김사월" and r["source"] == "A":
                if kind == "album":
                    log.append({"uts": r["uts"], "utc_time": r["utc_time"], "artist": "김사월", "source": "A", "field": "album", "old_title": "Romance", "new_title": "로맨스", "rule": "manual_merge", "changed_at": "now", "track": r["track"]})
                    r["album"] = "로맨스"
                else:
                    log.append({"uts": r["uts"], "utc_time": r["utc_time"], "artist": "김사월", "source": "A", "field": "track", "old_title": "Kiss", "new_title": "키스", "rule": "manual_merge", "changed_at": "now", "track": "Kiss"})
                    r["track"] = "키스"
        with open(d / "me_scrobbles.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=HEADER)
            w.writeheader()
            w.writerows(data)
        with open(d / "title_normalize_log.csv", "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=list(log[0]))
            w.writeheader()
            w.writerows(log)
        rules = d / "title_merge.txt"
        add_rule(rules, kind, "김사월", "Romance" if kind == "album" else "Kiss", "로맨스" if kind == "album" else "키스")
        return rules, pd.DataFrame(data)

    def run_undo(self, kind):
        with tempfile.TemporaryDirectory() as t:
            d = Path(t)
            rules, df = self.write_state(d, kind)
            variant, canonical = ("Romance", "로맨스") if kind == "album" else ("Kiss", "키스")
            self.assertEqual(restorable_rows(df, d, kind, "김사월", variant, canonical), 5)
            r = undo_merge(d, rules, kind, "김사월", variant, canonical)
            self.assertEqual(r["restored_rows"], 5)
            self.assertTrue((d / r["backup"]).exists())
            with open(d / "me_scrobbles.csv", newline="", encoding="utf-8-sig") as f:
                out = list(csv.DictReader(f))
            self.assertEqual(sum(1 for x in out if x[kind] == variant and x["artist"] == "김사월"), 5)
            self.assertEqual(load_rules(rules), [])
            with self.assertRaises(ValueError):
                undo_merge(d, rules, kind, "김사월", variant, canonical)

    def test_undo_album(self):
        self.run_undo("album")

    def test_undo_track(self):
        self.run_undo("track")


if __name__ == "__main__":
    unittest.main()
