"""artist_art.get_artist_art 테스트 (네트워크·실제 캐시 폴더를 쓰지 않는다). 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.lastfm import artist_art as ar  # noqa: E402


class Resp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def hit(name, pic="https://cdn/artist/abc123/500x500.jpg"):
    return {"name": name, "picture_big": pic}


class ArtistArtTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(ar, "CACHE_DIR", Path(self.tmp.name)), mock.patch.object(ar.time, "sleep")]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def get(self, payload, artist="Radiohead"):
        with mock.patch.object(ar.requests, "get", return_value=Resp(payload)) as g:
            return ar.get_artist_art(artist), g

    def test_exact_name_match_is_used_and_cached(self):
        r, _ = self.get({"data": [hit("Radiohead")]})
        self.assertEqual(r, {"url": "https://cdn/artist/abc123/500x500.jpg", "cached": False})
        r2, g2 = self.get({"data": []})
        self.assertTrue(r2["cached"])
        g2.assert_not_called()

    def test_name_match_ignores_case_spaces_and_punctuation(self):
        r, _ = self.get({"data": [hit("Tyler, The Creator")]}, "tyler the creator")
        self.assertIsNotNone(r["url"])

    def test_different_name_is_rejected_to_avoid_wrong_person(self):
        r, _ = self.get({"data": [hit("Radiohead Tribute Band")]})
        self.assertIsNone(r["url"])

    def test_picks_the_matching_result_not_just_the_first(self):
        r, _ = self.get({"data": [hit("Other", "https://cdn/artist/x/1.jpg"), hit("Radiohead", "https://cdn/artist/y/2.jpg")]})
        self.assertEqual(r["url"], "https://cdn/artist/y/2.jpg")

    def test_empty_deezer_placeholder_is_treated_as_missing(self):
        r, _ = self.get({"data": [hit("Radiohead", "https://cdn/artist//500x500.jpg")]})
        self.assertIsNone(r["url"])

    def test_miss_is_cached_then_retried_after_window(self):
        self.get({"data": []})
        r, g = self.get({"data": [hit("Radiohead")]})
        self.assertEqual(r, {"url": None, "cached": True})
        g.assert_not_called()
        with mock.patch.object(ar, "MISS_RETRY_SECONDS", -1):
            r, g = self.get({"data": [hit("Radiohead")]})
        g.assert_called_once()
        self.assertIsNotNone(r["url"])

    def test_error_response_and_network_failure_are_not_cached(self):
        self.get({"error": {"type": "Exception", "code": 4}})
        with mock.patch.object(ar.requests, "get", side_effect=OSError("down")):
            self.assertEqual(ar.get_artist_art("Radiohead"), {"url": None, "cached": False})
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_photo_name_mapping_searches_and_matches_the_mapped_name(self):
        with mock.patch.object(ar, "load_photo_names", return_value={"파란노을": "Parannoul"}):
            with mock.patch.object(ar.requests, "get", return_value=Resp({"data": [hit("Parannoul")]})) as g:
                r = ar.get_artist_art("파란노을")
        self.assertEqual(g.call_args.kwargs["params"]["q"], "Parannoul")
        self.assertIsNotNone(r["url"])

    def test_empty_name_skips_the_request(self):
        r, g = self.get({"data": [hit("")]}, "  ")
        self.assertIsNone(r["url"])
        g.assert_not_called()


if __name__ == "__main__":
    unittest.main()
