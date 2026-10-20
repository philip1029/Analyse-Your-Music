"""직접 지정한 커버(cover_overrides)와 누락 점검 테스트 (임시 폴더, 네트워크 없음). 실행:
    python3 -m unittest discover -s tests -v
"""

import base64
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis import cover_audit  # noqa: E402
from app.lastfm import album_art, cover_overrides as co  # noqa: E402


def data_url(fmt="PNG", size=(40, 30), mode="RGB", color=(200, 30, 30), mime=None):
    buf = io.BytesIO()
    Image.new(mode, size, color).save(buf, format=fmt)
    return f"data:image/{mime or fmt.lower()};base64," + base64.b64encode(buf.getvalue()).decode()


class OverrideTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [mock.patch.object(co, "COVERS_DIR", root / "covers"), mock.patch.object(co, "OVERRIDES_FILE", root / "o.json")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_set_get_and_clear_for_album_with_tolerant_key(self):
        self.assertIsNone(co.get_url("album", "Radiohead", "Kid A"))
        url = co.set_override("album", "Radiohead", "Kid A", data_url())
        self.assertRegex(url, r"^/api/cover-file/[0-9a-f]{40}\.jpg$")
        self.assertEqual(co.get_url("album", " radiohead ", "KID A"), url)               # 대소문자·공백 무시
        self.assertIsNone(co.get_url("album", "Radiohead", "Other"))
        self.assertTrue(co.file_path(url.rsplit("/", 1)[1]).is_file())
        self.assertTrue(co.clear_override("album", "radiohead", "kid a"))
        self.assertIsNone(co.get_url("album", "Radiohead", "Kid A"))
        self.assertFalse(co.clear_override("album", "Radiohead", "Kid A"))
        self.assertEqual(list((Path(self.tmp.name) / "covers").iterdir()), [])             # 안 쓰는 파일은 지워짐

    def test_artist_override_is_separate_from_album_override(self):
        co.set_override("artist", "Radiohead", None, data_url(color=(0, 0, 255)))
        self.assertIsNotNone(co.get_url("artist", "Radiohead"))
        self.assertIsNone(co.get_url("album", "Radiohead", "Radiohead"))

    def test_replacing_keeps_only_the_new_file_but_shared_files_stay(self):
        a = co.set_override("album", "A", "X", data_url(color=(1, 2, 3)))
        co.set_override("album", "B", "Y", data_url(color=(1, 2, 3)))                      # 같은 이미지(같은 해시) 공유
        co.clear_override("album", "A", "X")
        self.assertIsNotNone(co.file_path(a.rsplit("/", 1)[1]))                             # B 가 아직 쓰므로 남아야 함
        b2 = co.set_override("album", "B", "Y", data_url(color=(9, 9, 9)))
        self.assertNotEqual(a, b2)
        self.assertIsNone(co.file_path(a.rsplit("/", 1)[1]))                                # 이제 아무도 안 씀

    def test_large_and_transparent_images_are_normalized_to_jpeg(self):
        url = co.set_override("album", "A", "Big", data_url(size=(3000, 2000)))
        with Image.open(co.file_path(url.rsplit("/", 1)[1])) as im:
            self.assertEqual(im.format, "JPEG")
            self.assertLessEqual(max(im.size), co.MAX_SIDE)
        url2 = co.set_override("album", "A", "Alpha", data_url(mode="RGBA", color=(255, 0, 0, 0)))
        with Image.open(co.file_path(url2.rsplit("/", 1)[1])) as im2:
            self.assertEqual(im2.mode, "RGB")

    def test_invalid_inputs_are_rejected(self):
        bad = ["", "not a data url", "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=", "data:image/png;base64,@@@@",
               "data:image/png;base64," + base64.b64encode(b"not really an image").decode(),
               data_url(fmt="GIF", mime="png")]                                             # 선언은 png 인데 실제는 GIF
        for u in bad:
            with self.assertRaises(ValueError, msg=u[:40]):
                co.set_override("album", "A", "B", u)
        with self.assertRaises(ValueError):
            co.set_override("album", "", "B", data_url())
        with self.assertRaises(ValueError):
            co.set_override("song", "A", "B", data_url())
        with mock.patch.object(co, "MAX_BYTES", 10):
            with self.assertRaises(ValueError):
                co.set_override("album", "A", "B", data_url())

    def test_file_path_rejects_traversal_and_odd_names(self):
        for n in ("../../etc/passwd", "abc.jpg", "a" * 40 + ".png", "A" * 40 + ".jpg", ""):
            self.assertIsNone(co.file_path(n))


class AuditTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.patches = [mock.patch.object(co, "COVERS_DIR", root / "covers"), mock.patch.object(co, "OVERRIDES_FILE", root / "o.json"),
                        mock.patch.object(album_art, "CACHE_DIR", root / "albums")]
        (root / "albums").mkdir()
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def frame(self):
        rows = []
        for artist, album, n in (("A", "Found", 9), ("B", "Missed", 8), ("C", "Manual", 7), ("D", "Unchecked", 6), ("", "NoArtist", 5)):
            rows += [{"utc_time": "2026-01-01 00:00:00", "artist": artist, "album": album, "track": f"{album} {i}", "source": "L"} for i in range(n)]
        return pd.DataFrame(rows)

    def write_cache(self, artist, album, url):
        path = album_art._cache_path(artist, album)
        path.write_text('{"url": %s, "fetched_at": 1}' % ('"http://x/i.jpg"' if url else "null"), encoding="utf-8")

    def test_audit_sorts_albums_into_found_missing_manual_and_unchecked(self):
        self.write_cache("A", "Found", True)
        self.write_cache("B", "Missed", False)
        co.set_override("album", "C", "Manual", data_url())
        r = cover_audit.audit_albums(self.frame(), top=50)
        self.assertEqual((r["found"], r["manual"], r["unchecked"]), (1, 1, 1))
        self.assertEqual({m["name"]: m["reason"] for m in r["missing"]}, {"Missed": "자동으로 못 찾음", "NoArtist": "아티스트 정보가 없음"})

    def test_manual_override_removes_an_album_from_the_missing_list(self):
        self.write_cache("B", "Missed", False)
        co.set_override("album", "B", "Missed", data_url())
        names = {m["name"] for m in cover_audit.audit_albums(self.frame(), top=50)["missing"]}
        self.assertNotIn("Missed", names)

    def test_check_looks_up_only_unchecked_albums_up_to_the_limit(self):
        self.write_cache("A", "Found", True)
        with mock.patch.object(album_art, "get_album_art", return_value={"url": None, "cached": False}) as g:
            r = cover_audit.check_unchecked(self.frame(), "key", limit=5, top=50)
        self.assertEqual(g.call_count, 3)                                                  # Missed, Unchecked 둘 다 미조회 + C(Manual 아님: 미조회)
        self.assertEqual((r["checked"], r["found"], r["remaining"]), (3, 0, 0))


if __name__ == "__main__":
    unittest.main()
