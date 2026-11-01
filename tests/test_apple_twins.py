"""같은 재생의 A/L 쌍 찾기 규칙 테스트 (합성 데이터). 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

import dedupe_apple_twins as d  # noqa: E402


def row(uts, source, track="Song", artist="Art", album="Al"):
    return {"uts": str(uts), "artist": artist, "album": album, "track": track, "source": source}


class FindTwinsTest(unittest.TestCase):
    def test_pairs_within_gap_and_ignores_far_or_other_tracks(self):
        rows = [row(1000, "A"), row(1005, "L"), row(5000, "A"), row(5300, "L"), row(9000, "A", "Other"), row(9001, "L", "Different")]
        self.assertEqual(d.find_twins(rows), [(0, 1, 5)])

    def test_one_to_one_so_real_repeats_survive(self):
        # A 둘, L 하나: A 하나만 짝이 된다 (가까운 쪽)
        rows = [row(1000, "A"), row(1060, "A"), row(1058, "L")]
        self.assertEqual(d.find_twins(rows), [(1, 2, 2)])
        # A 둘, L 둘: 각자 짝
        rows = [row(1000, "A"), row(1060, "A"), row(1003, "L"), row(1064, "L")]
        self.assertEqual([(i, j) for i, j, _ in d.find_twins(rows)], [(0, 2), (1, 3)])

    def test_same_source_rows_are_never_paired(self):
        self.assertEqual(d.find_twins([row(1000, "A"), row(1005, "A"), row(1010, "L", "Other")]), [])
        self.assertEqual(d.find_twins([row(1000, "L"), row(1005, "L")]), [])

    def test_track_name_and_artist_matching(self):
        rows = [row(1000, "A", "Hey You!", "Pink Floyd"), row(1003, "L", "hey you", "pink floyd"),
                row(2000, "A", "Credit", "LIA & VISUAL ARTS / Key"), row(2002, "L", "Credit", "VISUAL ARTS / Key"),
                row(3000, "A", "Blank", ""), row(3001, "L", "Blank", "Someone"),
                row(4000, "A", "Same Title", "Artist One"), row(4001, "L", "Same Title", "Totally Different")]
        self.assertEqual([(i, j) for i, j, _ in d.find_twins(rows)], [(0, 1), (2, 3), (4, 5)])         # 아티스트가 완전히 다르면 짝이 아니다

    def test_max_gap_and_incomplete_rows(self):
        rows = [row(1000, "A"), row(1050, "L")]
        self.assertEqual(d.find_twins(rows, max_gap=30), [])
        self.assertEqual(len(d.find_twins(rows, max_gap=50)), 1)
        self.assertEqual(d.find_twins([{"uts": "", "track": "x", "source": "A"}, {"uts": "5", "track": "", "source": "L"}]), [])


if __name__ == "__main__":
    unittest.main()
