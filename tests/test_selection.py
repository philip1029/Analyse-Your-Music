"""analysis.selection (선택한 아티스트·앨범만 내보내기) 테스트. 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from io import StringIO
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis import selection as S  # noqa: E402


def frame():
    rows = []
    uts = 1_700_000_000

    def add(n, artist, album, track, day):
        nonlocal uts
        for i in range(n):
            uts += 600
            rows.append({"uts": uts, "utc_time": f"2026-01-{day:02d} {i % 24:02d}:10:00", "artist": artist, "album": album, "track": track, "source": "L"})

    add(5, "Radiohead", "Kid A", "Idioteque", 3)
    add(3, "Radiohead", "Kid A", "Optimistic", 4)
    add(4, "Radiohead", "OK Computer", "Lucky", 5)
    add(2, "Melvins", "Melvins", "Untitled", 6)
    add(3, "Radiohead", "Kid A", "Idioteque", 7)
    add(6, "Pink Floyd", "Animals", "Dogs", 8)
    return pd.DataFrame(rows)


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.df = frame()
        self.artist = {"kind": "artist", "name": "Radiohead"}
        self.album = {"kind": "album", "name": "Kid A", "artist": "Radiohead"}

    def test_normalize_drops_bad_and_duplicates(self):
        items = S.normalize_items([self.artist, {"kind": "artist", "name": " Radiohead "}, {"kind": "x", "name": "a"}, {"kind": "album", "name": ""}, "oops", self.album])
        self.assertEqual([i["kind"] for i in items], ["artist", "album"])
        self.assertIsNone(items[0]["artist"])

    def test_single_artist_rows(self):
        sel = S.select_df(self.df, [self.artist])
        self.assertEqual(len(sel), 15)
        self.assertEqual(set(sel["artist"]), {"Radiohead"})

    def test_album_rows_and_union_does_not_double_count(self):
        self.assertEqual(len(S.select_df(self.df, [self.album])), 11)
        self.assertEqual(len(S.select_df(self.df, [self.artist, self.album])), 15)     # 앨범은 아티스트의 부분집합

    def test_multi_selection_union(self):
        sel = S.select_df(self.df, [self.album, {"kind": "artist", "name": "Pink Floyd"}])
        self.assertEqual(len(sel), 11 + 6)

    def test_summary(self):
        s = S.summarize(self.df, S.normalize_items([self.artist, {"kind": "album", "name": "Nope", "artist": "Ghost"}]))
        self.assertEqual([i["found"] for i in s["items"]], [True, False])
        self.assertEqual(s["items"][0]["scrobbles"], 15)
        self.assertEqual((s["total"]["scrobbles"], s["total"]["library"]), (15, 23))
        self.assertEqual(s["items"][0]["first_played"], "2026-01-03")

    def test_csv_has_bom_kst_and_only_selected_rows(self):
        text = S.export_csv(self.df, [{"kind": "artist", "name": "Melvins", "artist": None}])
        self.assertTrue(text.startswith("﻿"))
        out = pd.read_csv(StringIO(text.lstrip("﻿")))
        self.assertEqual(len(out), 2)
        self.assertEqual(list(out.columns), ["uts", "utc_time", "kst_time", "artist", "album", "track", "source"])
        self.assertTrue((out["artist"] == "Melvins").all())
        self.assertEqual(out["kst_time"].iloc[0][:10], "2026-01-06")

    def test_csv_empty_selection_still_has_header(self):
        text = S.export_csv(self.df, [{"kind": "artist", "name": "Ghost", "artist": None}])
        self.assertEqual(len(text.lstrip("﻿").strip().splitlines()), 1)

    def test_prompt_contents(self):
        res = S.build_selection_prompt(self.df, [self.artist, self.album])
        self.assertEqual(res["scrobbles"], 15)
        p = res["prompt"]
        for needle in ("## 1. 선택 개요", "Radiohead - Kid A", "## 2. 월별 재생 추이", "Idioteque", "## 6. 분석 요청"):
            self.assertIn(needle, p)
        self.assertNotIn("Pink Floyd", p)                                    # 고르지 않은 아티스트는 나오지 않는다
        self.assertNotIn("Dogs", p)

    def test_prompt_none_when_nothing_found(self):
        self.assertIsNone(S.build_selection_prompt(self.df, [{"kind": "artist", "name": "Ghost"}])["prompt"])


if __name__ == "__main__":
    unittest.main()
