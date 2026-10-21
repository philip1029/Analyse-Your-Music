"""analysis.artist_fill (빈 artist 를 직접 채우기) 테스트. 합성 데이터만 쓴다. 실행:
    python3 -m unittest discover -s tests -v
"""

import csv
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis.artist_fill import apply_assignments, missing_groups, resolve_artist  # noqa: E402

HEADER = ["uts", "utc_time", "artist", "album", "track", "source"]


def rows():
    out = []
    n = [0]

    def add(count, artist, album, track, source="L"):
        for _ in range(count):
            n[0] += 1
            out.append({"uts": str(1000 + n[0]), "utc_time": f"2026-01-{(n[0] % 28) + 1:02d} 10:00:00", "artist": artist, "album": album, "track": track, "source": source})

    add(4, "Oasis", "Morning Glory", "Wonderwall")
    add(3, "", "Morning Glory", "Champagne Supernova", "A")        # 같은 앨범에서 Oasis 로 추정
    add(2, "", "Solo", "Intro", "A")                                  # 근거 없음
    add(2, "Pink Floyd", "WYWH", "Have a Cigar")
    add(1, "", "Other", "Have a Cigar", "A")                          # 같은 곡 이름으로 Pink Floyd 추정
    return out


def write(path, data):
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(data)


class MissingGroupsTest(unittest.TestCase):
    def test_groups_sorted_with_suggestions(self):
        r = missing_groups(pd.DataFrame(rows()))
        self.assertEqual((r["total_rows"], r["total_groups"]), (6, 3))
        first = r["items"][0]
        self.assertEqual((first["track"], first["count"]), ("Champagne Supernova", 3))
        self.assertEqual(first["suggestions"][0]["artist"], "Oasis")
        self.assertIn("같은 앨범", first["suggestions"][0]["reasons"])
        by = {i["track"]: i for i in r["items"]}
        self.assertEqual(by["Intro"]["suggestions"], [])
        self.assertEqual(by["Have a Cigar"]["suggestions"][0]["artist"], "Pink Floyd")
        self.assertEqual(by["Have a Cigar"]["suggestions"][0]["reasons"], ["같은 곡"])

    def test_nothing_missing(self):
        df = pd.DataFrame([r for r in rows() if r["artist"]])
        self.assertEqual(missing_groups(df)["items"], [])


class ResolveTest(unittest.TestCase):
    def test_merge_into_existing_spelling(self):
        counts = Counter({"Pink Floyd": 5, "pink  floyd": 1})
        self.assertEqual(resolve_artist(counts, " PINK-FLOYD "), ("Pink Floyd", True))
        self.assertEqual(resolve_artist(counts, "Pink Floyd"), ("Pink Floyd", False))
        self.assertEqual(resolve_artist(counts, "Oasis"), ("Oasis", False))

    def test_empty_name_rejected(self):
        with self.assertRaises(ValueError):
            resolve_artist(Counter(), "  ")


class ApplyTest(unittest.TestCase):
    def test_apply_fills_only_matching_empty_rows_with_backup_and_log(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            csv_path = data / "me_scrobbles.csv"
            write(csv_path, rows())
            r = apply_assignments(data, [{"track": "Champagne Supernova", "album": "Morning Glory", "artist": "oasis"}, {"track": "Intro", "album": "Solo", "artist": ""}])
            self.assertEqual(r["applied_rows"], 3)
            self.assertTrue(r["details"][0]["merged"])
            self.assertEqual(r["details"][0]["artist"], "Oasis")       # 기존 표기로 합쳐짐
            self.assertTrue((data / r["backup"]).exists())
            with open(csv_path, newline="", encoding="utf-8-sig") as f:
                out = list(csv.DictReader(f))
            self.assertEqual(sum(1 for x in out if x["artist"] == ""), 3)  # Intro(2) + Have a Cigar(1) 은 그대로
            self.assertTrue(all(x["source"] == "A" for x in out if x["track"] == "Champagne Supernova"))   # source 는 그대로
            with open(data / "artist_fill_log.csv", newline="", encoding="utf-8-sig") as f:
                log = list(csv.DictReader(f))
            self.assertEqual(len(log), 3)
            self.assertEqual(log[0]["rule"], "manual:ui:merged")

    def test_no_match_changes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            data = Path(d)
            write(data / "me_scrobbles.csv", rows())
            r = apply_assignments(data, [{"track": "Nope", "album": "", "artist": "X"}])
            self.assertEqual(r, {"applied_rows": 0, "backup": None, "details": []})
            self.assertFalse(list(data.glob("*.bak*")))


if __name__ == "__main__":
    unittest.main()
