"""A/L 이 아닌 source(M = 보관함의 로컬 파일 재생 등)가 섞인 CSV 도 정리 스크립트들이 깨지지 않는지. 실행:
    python3 -m unittest discover -s tests -v
"""

import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
HEADER = ["uts", "utc_time", "artist", "album", "track", "source"]


def rows():
    out = []
    for i, (artist, album, track, source) in enumerate([
        ("Les Rallizes Dénudés", "Live", "Night", "A"),
        ("Les Rallizes Denudes", "Live", "Night", "M"),
        ("Les Rallizes Dénudés", "Live", "Night", "L"),
        ("Pet Shop", "Album", "Song One", "L"),
        ("Pet Shop", "Album", "song one", "M"),
        ("Gabba-Eater", "Hard", "Track", "M"),
        ("GABBA-EATER", "Hard", "Track", "L"),
    ]):
        out.append({"uts": str(1_700_000_000 - i * 600), "utc_time": "2026-01-01 00:00:00", "artist": artist, "album": album, "track": track, "source": source})
    return out


class OtherSourceTest(unittest.TestCase):
    def run_script(self, name, *args):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x_scrobbles.csv"
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=HEADER)
                w.writeheader()
                w.writerows(rows())
            empty = Path(tmp) / "empty.txt"
            empty.write_text("", encoding="utf-8")
            extra = ["--keep-separate", str(empty), "--manual-merge", str(empty), "--canonical-file", str(Path(tmp) / "canonical.txt")] if name == "normalize_artists.py" else []
            res = subprocess.run([sys.executable, str(SCRIPTS / name), "--data-dir", tmp, *extra, *args], capture_output=True, text=True, timeout=60)
            after = path.read_text(encoding="utf-8-sig") if path.exists() else ""
        return res, after

    def test_normalize_artists_dry_run_and_apply(self):
        res, _ = self.run_script("normalize_artists.py")
        self.assertEqual(res.returncode, 0, res.stderr)
        res, after = self.run_script("normalize_artists.py", "--apply")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertNotIn("Gabba-Eater", after)                      # M 행도 통일 표기(GABBA-EATER)로 바뀐다
        self.assertIn(",M", after)                                  # source 열은 그대로

    def test_normalize_titles_dry_run_and_apply(self):
        res, _ = self.run_script("normalize_titles.py")
        self.assertEqual(res.returncode, 0, res.stderr)
        res, _ = self.run_script("normalize_titles.py", "--apply")
        self.assertEqual(res.returncode, 0, res.stderr)


if __name__ == "__main__":
    unittest.main()
