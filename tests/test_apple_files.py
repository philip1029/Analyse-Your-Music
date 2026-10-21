"""apple_files (Apple 폴더 안내 · 다른 위치의 파일 가져오기) 테스트. 임시 폴더만 쓴다. 실행:
    python3 -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import apple_files  # noqa: E402


class ChecklistTest(unittest.TestCase):
    def test_marks_found_files_and_reports_size(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "Apple Music Play Activity.csv").write_text("a,b\n1,2\n", encoding="utf-8")
            (Path(d) / "Apple Music Library Tracks.json").write_text("[]", encoding="utf-8")
            r = apple_files.checklist(d)
            by = {f["key"]: f for f in r["files"]}
            self.assertEqual(r["folder"], d)
            self.assertEqual(by["play_activity"]["found"], "Apple Music Play Activity.csv")
            self.assertEqual(by["library_tracks"]["found"], "Apple Music Library Tracks.json")      # .json 도 인정
            self.assertIsNone(by["library_xml"]["found"])
            self.assertTrue(all(f["purpose"] and f["source"] for f in r["files"]))

    def test_no_folder(self):
        r = apple_files.checklist(None)
        self.assertEqual(r["folder"], "")
        self.assertTrue(all(f["found"] is None for f in r["files"]))


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.apple = self.root / "apple"
        self.apple.mkdir()
        self.other = self.root / "downloads"
        self.other.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_copies_zip_from_a_folder_and_keeps_original(self):
        sub = self.other / "export" / "inner"
        sub.mkdir(parents=True)
        z = sub / "Apple Music Library Tracks.json.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("Apple Music Library Tracks.json", json.dumps([{"Title": "x"}]))
        r = apple_files.import_file(str(self.apple), str(self.other), "library_tracks")      # 폴더를 줘도 안에서 찾는다
        self.assertEqual(r["copied"], "Apple Music Library Tracks.json.zip")
        self.assertTrue((self.apple / r["copied"]).exists())
        self.assertTrue(z.exists())

    def test_xml_with_any_name_gets_the_standard_name(self):
        src = self.other / "내 라이브러리.xml"
        src.write_text('<?xml version="1.0"?><plist></plist>', encoding="utf-8")
        r = apple_files.import_file(str(self.apple), str(src), "library_xml")
        self.assertEqual(r["copied"], "전체.xml")

    def test_refuses_overwrite_unless_confirmed(self):
        src = self.other / "a.xml"
        src.write_text('<?xml version="1.0"?><plist/>', encoding="utf-8")
        apple_files.import_file(str(self.apple), str(src), "library_xml")
        with self.assertRaises(FileExistsError):
            apple_files.import_file(str(self.apple), str(src), "library_xml")
        apple_files.import_file(str(self.apple), str(src), "library_xml", overwrite=True)

    def test_rejects_wrong_kind_empty_and_fake_files(self):
        csv_file = self.other / "x.csv"
        csv_file.write_text("a,b\n", encoding="utf-8")
        with self.assertRaises(ValueError):                                   # xml 자리에 csv
            apple_files.import_file(str(self.apple), str(csv_file), "library_xml")
        fake = self.other / "fake.xml"
        fake.write_text("그냥 텍스트", encoding="utf-8")
        with self.assertRaises(ValueError):
            apple_files.import_file(str(self.apple), str(fake), "library_xml")
        empty = self.other / "empty.xml"
        empty.write_text("", encoding="utf-8")
        with self.assertRaises(ValueError):
            apple_files.import_file(str(self.apple), str(empty), "library_xml")
        with self.assertRaises(ValueError):
            apple_files.import_file(str(self.apple), str(self.other / "nope.xml"), "library_xml")
        with self.assertRaises(ValueError):
            apple_files.import_file(str(self.apple), str(csv_file), "unknown")

    def test_needs_apple_folder_and_rejects_same_location(self):
        src = self.other / "a.xml"
        src.write_text("<?xml version='1.0'?>", encoding="utf-8")
        with self.assertRaises(ValueError):
            apple_files.import_file(None, str(src), "library_xml")
        inside = self.apple / "전체.xml"
        inside.write_text("<?xml version='1.0'?>", encoding="utf-8")
        with self.assertRaises(ValueError):                                   # 이미 그 위치
            apple_files.import_file(str(self.apple), str(inside), "library_xml")


if __name__ == "__main__":
    unittest.main()
