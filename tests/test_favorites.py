"""analysis.favorites (좋아요 곡 저장·조회·가져오기) 테스트. 실행:
    python3 -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from app.analysis import favorites  # noqa: E402
import import_favorites  # noqa: E402


def frame():
    rows = []

    def add(n, artist, album, track, day):
        for i in range(n):
            rows.append({"uts": 0, "utc_time": f"2026-01-{day:02d} {i % 24:02d}:00:00", "artist": artist, "album": album, "track": track, "source": "L"})

    add(5, "King Crimson", "Red", "Matte Kudasai", 3)
    add(4, "VISUAL ARTS / Key", "Air OST", "Tori No Uta", 6)
    add(2, "LIA & VISUAL ARTS / Key", "Air OST", "Tori no uta", 7)
    add(2, "Melvins", "Melvins", "Untitled", 8)
    add(3, "Radiohead", "Kid A", "Untitled", 9)
    return pd.DataFrame(rows)


class FavoritesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "favorites.json"
        self.df = frame()

    def tearDown(self):
        self.tmp.cleanup()

    def test_add_and_list(self):
        self.assertTrue(favorites.set_favorite(self.path, self.df, "King Crimson", "Matte Kudasai", True))
        items = favorites.list_favorites(self.path, self.df)
        self.assertEqual(len(items), 1)
        self.assertEqual((items[0]["artist"], items[0]["name"], items[0]["scrobbles"]), ("King Crimson", "Matte Kudasai", 5))
        self.assertEqual(items[0]["first_played"], "2026-01-03")
        self.assertTrue(items[0]["found"])

    def test_toggle_is_idempotent(self):
        favorites.set_favorite(self.path, self.df, "King Crimson", "Matte Kudasai", True)
        self.assertFalse(favorites.set_favorite(self.path, self.df, "King Crimson", "Matte Kudasai", True))
        self.assertEqual(len(favorites.load(self.path)), 1)
        self.assertTrue(favorites.set_favorite(self.path, self.df, "King Crimson", "Matte Kudasai", False))
        self.assertFalse(favorites.set_favorite(self.path, self.df, "King Crimson", "Matte Kudasai", False))
        self.assertEqual(favorites.load(self.path), [])

    def test_spelling_variants_are_one_favorite(self):
        # 크레딧 표기와 대소문자만 다른 같은 곡은 하나로 센다
        favorites.set_favorite(self.path, self.df, "VISUAL ARTS / Key", "Tori No Uta", True)
        self.assertFalse(favorites.set_favorite(self.path, self.df, "LIA & VISUAL ARTS / Key", "Tori no uta", True))
        items = favorites.list_favorites(self.path, self.df)
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["scrobbles"], 6)
        self.assertEqual(set(items[0]["artists"]), {"VISUAL ARTS / Key", "LIA & VISUAL ARTS / Key"})
        # 다른 표기로도 끌 수 있다
        self.assertTrue(favorites.set_favorite(self.path, self.df, "LIA & VISUAL ARTS / Key", "Tori no uta", False))
        self.assertEqual(favorites.load(self.path), [])

    def test_same_title_other_artist_is_separate(self):
        favorites.set_favorite(self.path, self.df, "Melvins", "Untitled", True)
        items = favorites.list_favorites(self.path, self.df)
        self.assertEqual((items[0]["artist"], items[0]["scrobbles"]), ("Melvins", 2))
        self.assertFalse(favorites.set_favorite(self.path, self.df, "Radiohead", "Untitled", False))   # Radiohead 쪽은 안 눌렀다
        self.assertEqual(len(favorites.load(self.path)), 1)

    def test_missing_track_is_kept_but_not_found(self):
        favorites.set_favorite(self.path, self.df, "Nobody", "Nothing", True)
        items = favorites.list_favorites(self.path, self.df)
        self.assertEqual(len(items), 1)
        self.assertFalse(items[0]["found"])
        self.assertEqual(items[0]["scrobbles"], 0)

    def test_empty_title_rejected(self):
        with self.assertRaises(ValueError):
            favorites.set_favorite(self.path, self.df, "A", "  ", True)

    def test_corrupt_file_reads_as_empty(self):
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(favorites.load(self.path), [])
        favorites.set_favorite(self.path, self.df, "King Crimson", "Matte Kudasai", True)
        self.assertEqual(len(json.loads(self.path.read_text(encoding="utf-8"))), 1)

    def test_parse_line(self):
        self.assertEqual(favorites.parse_line("A - B - C"), ("A - B", "C"))
        self.assertEqual(favorites.parse_line("Only title"), ("Only title", ""))
        self.assertIsNone(favorites.parse_line("   "))

    def test_find_track_and_import_matching(self):
        res = import_favorites.match_lines(self.df, ["matte kudasai - king crimson", "Untitled - Melvins", "Untitled", "Ghost - Nobody"])
        self.assertEqual([r["status"] for r in res], ["ok", "ok", "ambiguous", "none"])
        self.assertEqual(res[1]["cands"][0]["artist"], "Melvins")

    def test_find_track_ignores_artist_credit_format(self):
        cands = favorites.find_track(self.df, "Tori no Uta", "Lia & Visual Arts / Key")
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["count"], 6)


if __name__ == "__main__":
    unittest.main()
