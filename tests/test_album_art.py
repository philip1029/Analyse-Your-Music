"""album_art.get_album_art 테스트 (네트워크·실제 캐시 폴더를 쓰지 않는다). 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.lastfm import album_art as aa  # noqa: E402

IMAGES = [
    {"#text": "http://x/i/u/34s/h.jpg", "size": "small"},
    {"#text": "http://x/i/u/174s/h.jpg", "size": "large"},
    {"#text": "http://x/i/u/300x300/h.jpg", "size": "extralarge"},
    {"#text": "http://x/i/u/300x300/h.jpg", "size": "mega"},
]


class Resp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class AlbumArtTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(aa, "CACHE_DIR", Path(self.tmp.name)), mock.patch.object(aa.time, "sleep")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def get(self, payload, artist="A", album="B"):
        with mock.patch.object(aa.requests, "get", return_value=Resp(payload)) as g:
            return aa.get_album_art(artist, album, "key"), g

    def test_picks_extralarge_and_caches(self):
        r, g = self.get({"album": {"image": IMAGES}})
        self.assertEqual(r, {"url": "http://x/i/u/300x300/h.jpg", "cached": False})
        r2, g2 = self.get({"album": {"image": []}})            # 두 번째는 캐시에서
        self.assertEqual(r2, {"url": "http://x/i/u/300x300/h.jpg", "cached": True})
        g2.assert_not_called()

    def test_cache_key_ignores_case_and_edge_spaces(self):
        self.get({"album": {"image": IMAGES}}, "Artist", "Album")
        r, g = self.get({"album": {"image": []}}, " artist ", "ALBUM")
        self.assertTrue(r["cached"])
        g.assert_not_called()

    def test_empty_images_cached_as_miss(self):
        r, _ = self.get({"album": {"image": [{"#text": "", "size": "extralarge"}]}})
        self.assertEqual(r, {"url": None, "cached": False})
        r2, g2 = self.get({"album": {"image": IMAGES}})
        self.assertEqual(r2, {"url": None, "cached": True})      # 재시도 기간 안에는 다시 묻지 않는다
        g2.assert_not_called()

    def test_miss_is_retried_after_retry_window(self):
        self.get({"error": 6, "message": "Album not found"})
        with mock.patch.object(aa, "MISS_RETRY_SECONDS", -1):
            r, g = self.get({"album": {"image": IMAGES}})
        g.assert_called_once()
        self.assertEqual(r["url"], "http://x/i/u/300x300/h.jpg")

    def test_placeholder_image_is_treated_as_missing(self):
        ph = [{"#text": f"http://x/i/u/300x300/{aa.PLACEHOLDER_HASH}.png", "size": "extralarge"}]
        r, _ = self.get({"album": {"image": ph}})
        self.assertIsNone(r["url"])

    def test_transient_error_is_not_cached(self):
        self.get({"error": 29, "message": "Rate limit exceeded"})
        r, g = self.get({"album": {"image": IMAGES}})
        g.assert_called_once()
        self.assertEqual(r["url"], "http://x/i/u/300x300/h.jpg")

    def test_network_failure_is_not_cached(self):
        with mock.patch.object(aa.requests, "get", side_effect=OSError("down")):
            self.assertEqual(aa.get_album_art("A", "B", "key"), {"url": None, "cached": False})
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_missing_artist_or_album_skips_the_request(self):
        for a, b in (("", "B"), ("A", ""), (None, None)):
            r, g = self.get({"album": {"image": IMAGES}}, a, b)
            self.assertIsNone(r["url"])
            g.assert_not_called()

    def test_japanese_names_get_distinct_cache_files(self):
        self.assertNotEqual(aa._cache_path("コハナ", "単品"), aa._cache_path("近藤", "別"))


if __name__ == "__main__":
    unittest.main()
