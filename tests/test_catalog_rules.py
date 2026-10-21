"""카탈로그 식별자가 없는 곡을 애플 로그 기반 제거 규칙에서 빼는 예외 테스트.

합성 데이터만 쓰므로 개인 데이터가 필요 없다. 실행:
    python3 -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import detect_fake_scrobbles as det  # noqa: E402
import preprocess as pp  # noqa: E402


def track(title, artist, catalog_id=None):
    t = {"Title": title, "Artist": artist}
    if catalog_id is not None:
        t["Apple Music Track Identifier"] = catalog_id
    return t


class CatalogIndexTest(unittest.TestCase):
    def test_catalog_track_is_not_flagged(self):
        idx = det.CatalogIndex([track("Song", "A", "123")])
        self.assertFalse(idx.is_noncatalog("A", "Song"))

    def test_missing_identifier_is_noncatalog(self):
        idx = det.CatalogIndex([track("Song", "A"), track("Other", "A", ""), track("Third", "A", "nan")])
        self.assertTrue(idx.is_noncatalog("A", "Song"))
        self.assertTrue(idx.is_noncatalog("A", "Other"))       # 빈 문자열
        self.assertTrue(idx.is_noncatalog("A", "Third"))       # 문자열 "nan"

    def test_track_not_in_library_keeps_old_rules(self):
        idx = det.CatalogIndex([track("Song", "A")])
        self.assertFalse(idx.is_noncatalog("A", "Unknown"))    # 라이브러리에 없으면 스트리밍 곡으로 본다

    def test_same_title_other_artist_uses_artist_key(self):
        idx = det.CatalogIndex([track("Intro", "X", "1"), track("Intro", "Y")])
        self.assertTrue(idx.is_noncatalog("Y", "Intro"))
        self.assertFalse(idx.is_noncatalog("X", "Intro"))

    def test_title_fallback_when_artist_spelling_differs(self):
        idx = det.CatalogIndex([track("Yoshi", "Koji Kondo")])
        self.assertTrue(idx.is_noncatalog("近藤浩治", "Yoshi"))          # 아티스트 표기만 다름
        mixed = det.CatalogIndex([track("Intro", "X", "1"), track("Intro", "Y")])
        self.assertFalse(mixed.is_noncatalog("Z", "Intro"))             # 같은 곡명에 카탈로그 곡이 있으면 폴백 안 함

    def test_load_from_zip_and_missing_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "Apple Music Library Tracks.json.zip"
            with zipfile.ZipFile(p, "w") as z:
                z.writestr("Apple Music Library Tracks.json", json.dumps([track("Song", "A")]))
            idx = det.load_catalog_index(str(p))
            self.assertTrue(idx.is_noncatalog("A", "Song"))
            self.assertIsNone(det.load_catalog_index(str(Path(d) / "nope.zip")))
            self.assertIsNone(det.load_catalog_index(None))


def make_run(artist, trk, gap=200, n=3):
    utses = [1_000_000 + gap * i for i in range(n)]
    return {"artist": artist, "track": trk, "gap": gap, "count": n, "row_ids": list(range(n)),
            "utses": utses, "start_uts": utses[0], "end_uts": utses[-1]}


class ClassifyRunTest(unittest.TestCase):
    def classify(self, run, idx):
        return det.classify_run(run, {run["track"]: {run["gap"]}}, defaultdict(Counter),
                                defaultdict(int), True, None, idx)

    def test_noncatalog_run_is_unverifiable_and_nothing_removed(self):
        idx = det.CatalogIndex([track("Intro", "Y")])
        r = self.classify(make_run("Y", "Intro"), idx)
        self.assertEqual(r["classification"], "UNVERIFIABLE")
        self.assertEqual(r["rows_to_remove"], [])
        self.assertEqual(r["rows_to_keep"], [0, 1, 2])

    def test_catalog_run_is_still_removed_when_log_has_no_play(self):
        idx = det.CatalogIndex([track("Intro", "Y", "9")])
        r = self.classify(make_run("Y", "Intro"), idx)
        self.assertEqual(r["classification"], "REMOVE")
        self.assertEqual(r["rows_to_remove"], [0, 1, 2])

    def test_without_index_behaves_as_before(self):
        r = self.classify(make_run("Y", "Intro"), None)
        self.assertEqual(r["classification"], "REMOVE")

    def test_long_noncatalog_run_is_also_kept(self):                       # A안: 5회 이상도 지우지 않음
        idx = det.CatalogIndex([track("Intro", "Y")])
        r = self.classify(make_run("Y", "Intro", n=7), idx)
        self.assertEqual(r["classification"], "UNVERIFIABLE")
        self.assertEqual(r["rows_to_remove"], [])


class _Durations:
    def candidates(self, artist, trk):
        return {200}, "local"


class PreprocessJudgeTest(unittest.TestCase):
    def judge(self, idx):
        rows = [{"uts": str(1_000_000 + 200 * i), "artist": "Y", "track": "Intro", "album": "", "source": "L"}
                for i in range(3)]
        state = {"frozen_through_uts": 0, "provisional_through_uts": 0}
        log = {"counts": defaultdict(int), "end_uts": 10 ** 10, "catalog": idx, "durations": {}}
        return pp.judge(rows, state, log, lambda need: _Durations(), None)

    def test_noncatalog_goes_to_pending_not_removed(self):
        removals, pending, _ = self.judge(det.CatalogIndex([track("Intro", "Y")]))
        self.assertEqual(removals, {})
        self.assertEqual(pending["noncatalog_unverifiable"], 1)

    def test_catalog_track_still_removed(self):
        removals, pending, _ = self.judge(det.CatalogIndex([track("Intro", "Y", "9")]))
        self.assertEqual(len(removals), 3)
        self.assertEqual({v["rule"] for v in removals.values()}, {"log:no_play"})
        self.assertNotIn("noncatalog_unverifiable", pending)

    def test_no_index_keeps_previous_behavior(self):
        removals, _, _ = self.judge(None)
        self.assertEqual(len(removals), 3)


if __name__ == "__main__":
    unittest.main()
