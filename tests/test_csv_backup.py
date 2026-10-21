"""csv_backup (gzip 백업 + 종류별 보관 개수 + 정리/복원) 테스트. 임시 폴더의 합성 CSV 만 쓴다. 실행:
    python3 -m unittest discover -s tests -v
"""

import gzip
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import csv_backup  # noqa: E402


class CsvBackupTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.csv = self.dir / "user_scrobbles.csv"
        self.csv.write_text("uts,artist,track\n1,A,x\n2,B,y\n", encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def _fake_old(self, kind, stamp, gz=False):
        """과거 시각의 백업을 흉내 낸다."""
        name = f"{self.csv.name}.bak_{kind}_{stamp}" + (".gz" if gz else "")
        p = self.dir / name
        if gz:
            with gzip.open(p, "wb") as f:
                f.write(self.csv.read_bytes())
        else:
            p.write_bytes(self.csv.read_bytes())
        return p

    def test_make_backup_is_gzip_with_same_content(self):
        backup = csv_backup.make_backup(self.csv, "titlenorm")
        self.assertTrue(backup.name.startswith("user_scrobbles.csv.bak_titlenorm_"))
        self.assertEqual(backup.suffix, ".gz")
        self.assertEqual(csv_backup.read_backup(backup), self.csv.read_bytes())

    def test_keeps_only_latest_n_per_kind(self):
        for i in range(7):
            self._fake_old("artistnorm", f"2026010{i + 1}_000000", gz=True)
        other = self._fake_old("titlenorm", "20260101_000000", gz=True)
        with mock.patch.dict(os.environ, {"BACKUP_KEEP": "3"}):
            csv_backup.make_backup(self.csv, "artistnorm")
        mine = csv_backup.list_backups(self.csv, "artistnorm")
        self.assertEqual(len(mine), 3)
        self.assertTrue(other.exists())            # 다른 종류는 건드리지 않는다

    def test_make_backup_does_not_delete_legacy_uncompressed(self):
        legacy = [self._fake_old("titlenorm", f"2026010{i}_000000") for i in range(1, 9)]
        with mock.patch.dict(os.environ, {"BACKUP_KEEP": "2"}):
            csv_backup.make_backup(self.csv, "titlenorm")
        self.assertTrue(all(p.exists() for p in legacy))

    def test_keep_count_defaults_and_ignores_garbage(self):
        with mock.patch.dict(os.environ, {"BACKUP_KEEP": "abc"}):
            self.assertEqual(csv_backup.keep_count(), csv_backup.DEFAULT_KEEP)
        with mock.patch.dict(os.environ, {"BACKUP_KEEP": "0"}):
            self.assertEqual(csv_backup.keep_count(), 1)

    def test_clean_plan_and_apply(self):
        old = [self._fake_old("titlenorm", f"2026010{i}_000000") for i in range(1, 6)]
        with mock.patch.dict(os.environ, {"BACKUP_KEEP": "2"}):
            plan = csv_backup.plan_clean(self.csv)
            self.assertEqual(plan["delete"], old[:3])
            self.assertEqual(plan["compress"], old[3:])
            self.assertTrue(all(p.exists() for p in old))          # 계획만 세웠을 땐 그대로
            csv_backup.apply_clean(plan)
        self.assertFalse(any(p.exists() for p in old))
        left = csv_backup.list_backups(self.csv)
        self.assertEqual(len(left), 2)
        self.assertTrue(all(p.suffix == ".gz" for p in left))
        self.assertEqual(csv_backup.read_backup(left[0]), self.csv.read_bytes())

    def test_restore_returns_old_content_and_saves_current(self):
        backup = csv_backup.make_backup(self.csv, "artistfill")
        original = self.csv.read_bytes()
        self.csv.write_text("uts,artist,track\n9,Z,z\n", encoding="utf-8")
        safety = csv_backup.restore_backup(self.csv, backup)
        self.assertEqual(self.csv.read_bytes(), original)
        self.assertIn("prerestore", safety.name)
        self.assertIn(b"9,Z,z", csv_backup.read_backup(safety))

    def test_restore_from_legacy_uncompressed(self):
        legacy = self._fake_old("preprocess", "20260101_000000")
        self.csv.write_text("changed\n", encoding="utf-8")
        csv_backup.restore_backup(self.csv, legacy)
        self.assertIn(b"1,A,x", self.csv.read_bytes())

    def test_unrelated_files_are_ignored(self):
        (self.dir / "user_scrobbles.csv.bak").write_text("x")
        (self.dir / "other.csv.bak_titlenorm_20260101_000000").write_text("x")
        self.assertEqual(csv_backup.list_backups(self.csv), [])


if __name__ == "__main__":
    unittest.main()
