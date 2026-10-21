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

from app.analysis.title_merge import add_rule, album_pairing, artist_album_pairing, merged_artist_overview, bulk_check, load_rules, preview, restorable_rows, restore_rules, titles_of, undo_merge, unpaired_albums  # noqa: E402
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


def album_frame():
    out = []
    n = [0]

    def add(count, album, track, source, artist="김사월"):
        for _ in range(count):
            n[0] += 1
            out.append({"uts": str(5000 + n[0]), "utc_time": f"t{n[0]}", "artist": artist, "album": album, "track": track, "source": source})

    add(4, "로맨스", "Orange", "A")        # 영문(Apple) 제목들
    add(3, "로맨스", "Prague", "A")
    add(2, "로맨스", "We", "A")
    add(1, "로맨스", "오렌지", "L")        # 한글(Last.fm) 제목들
    add(1, "로맨스", "프라하", "L")
    add(1, "로맨스", "우리", "L")
    add(1, "로맨스", "키스", "L")
    add(3, "Done", "Same", "A")
    add(1, "Done", "Same", "L")            # 이미 한 제목으로 맞춰진 앨범
    return pd.DataFrame(out)


DUR = {("김사월", "Orange"): 179, ("김사월", "오렌지"): 180, ("김사월", "Prague"): 151, ("김사월", "프라하"): 151, ("김사월", "We"): 163, ("김사월", "우리"): 300}


class PairingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.rules = Path(self.tmp.name) / "title_merge.txt"
        self.df = album_frame()

    def tearDown(self):
        self.tmp.cleanup()

    def test_only_albums_with_unpaired_titles_on_both_sides(self):
        albums = unpaired_albums(self.df, "김사월")
        self.assertEqual([a["album"] for a in albums], ["로맨스"])
        self.assertEqual((albums[0]["a_only"], albums[0]["l_only"]), (3, 4))

    def test_pairing_suggests_only_unique_duration_matches(self):
        r = album_pairing(self.df, "김사월", "로맨스", lambda a, t: DUR.get((a, t)))
        left = {x["title"]: x for x in r["left"]}
        self.assertEqual([x["title"] for x in r["left"]], ["Orange", "Prague", "We"])          # 많이 들은 순
        self.assertEqual(left["Orange"]["suggestion"]["title"], "오렌지")                       # 179 vs 180 → ±2초
        self.assertEqual(left["Prague"]["suggestion"]["title"], "프라하")
        self.assertIsNone(left["We"]["suggestion"])                                            # 163 vs 300 → 불일치
        self.assertEqual({x["title"] for x in r["right"]}, {"오렌지", "프라하", "우리", "키스"})

    def test_no_duration_means_no_suggestion(self):
        r = album_pairing(self.df, "김사월", "로맨스", lambda a, t: None)
        self.assertTrue(all(x["suggestion"] is None for x in r["left"]))

    def test_bulk_check_skips_bad_pairs_with_reasons(self):
        pairs = [
            {"variant": "Orange", "canonical": "오렌지"},
            {"variant": "Prague", "canonical": "프라하"},
            {"variant": "Prague", "canonical": "키스"},          # 같은 곡 두 번
            {"variant": "We", "canonical": "Orange"},             # 통일 표기(Orange)가 다른 쌍의 변형
            {"variant": "Nope", "canonical": "오렌지"},           # 기록에 없음
        ]
        ok, skipped = bulk_check(self.df, "김사월", pairs, self.rules)
        self.assertEqual([(p["variant"], p["rows"]) for p in ok], [("Orange", 4), ("Prague", 3)])
        reasons = {s["variant"]: s["reason"] for s in skipped}
        self.assertIn("두 번", reasons["Prague"])
        self.assertIn("없는", reasons["Nope"])
        self.assertIn("다른 곡", reasons["We"])

    def test_merged_artist_overview_counts_remaining_pairing(self):
        df = pd.concat([self.df, pd.DataFrame([{"uts": "9", "utc_time": "t", "artist": "김사월", "album": "Romance", "track": "Orange", "source": "A"}, {"uts": "10", "utc_time": "t", "artist": "김사월", "album": "Heaven", "track": "x", "source": "L"}])])
        out = merged_artist_overview(df, {"Kim Sawol": "김사월", "Ghost": "없는 아티스트"})
        self.assertEqual([o["artist"] for o in out], ["김사월"])           # 기록에 없는 통일 이름은 뺀다
        self.assertEqual(out[0]["merged_from"], ["Kim Sawol"])
        self.assertEqual((out[0]["albums"], out[0]["track_albums"]), (1, 1))   # Romance(A만) 1개, 곡 짝짓기할 앨범 로맨스 1개

    def test_album_pairing_and_bulk_for_albums(self):
        df = pd.concat([self.df, pd.DataFrame([{"uts": "9", "utc_time": "t", "artist": "김사월", "album": "Romance", "track": "Orange", "source": "A"}, {"uts": "10", "utc_time": "t", "artist": "김사월", "album": "Heaven", "track": "x", "source": "L"}])])
        r = artist_album_pairing(df, "김사월")
        self.assertEqual({a["title"] for a in r["left"]}, {"Romance"})
        self.assertIn("Heaven", {a["title"] for a in r["right"]})
        ok, skipped = bulk_check(df, "김사월", [{"variant": "Romance", "canonical": "Heaven"}], self.rules, "album")
        self.assertEqual((len(ok), skipped), (1, []))


if __name__ == "__main__":
    unittest.main()
