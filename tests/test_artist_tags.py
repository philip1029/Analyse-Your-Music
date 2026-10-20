"""아티스트 태그 조회(client.get_artist_top_tags)의 캐시 규칙과 fill_artist_tags 의 대상 선정 테스트. 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from app.lastfm import client  # noqa: E402
import fill_artist_tags as fat  # noqa: E402


class Resp:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


TAGS = {"toptags": {"tag": [{"name": "shoegaze", "count": "100"}, {"name": "", "count": "5"}]}}


class TagCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patches = [mock.patch.object(client, "CACHE_DIR", Path(self.tmp.name)), mock.patch.object(client.time, "sleep"),
                        mock.patch.object(client, "resolve_artist_name", side_effect=lambda n: n)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def get(self, payload=None, error=None):
        with mock.patch.object(client.requests, "get", side_effect=error, return_value=Resp(payload)) as g:
            return client.get_artist_top_tags("Slowdive", "key"), g

    def test_found_tags_are_cleaned_and_cached(self):
        tags, _ = self.get(TAGS)
        self.assertEqual(tags, [{"name": "shoegaze", "count": 100}])
        again, g = self.get({"error": 29})
        self.assertEqual(again, tags)
        g.assert_not_called()

    def test_not_found_artist_is_cached_as_no_tags(self):
        tags, _ = self.get({"error": 6, "message": "The artist you supplied could not be found"})
        self.assertEqual(tags, [])
        self.assertTrue(client.CACHE_DIR.joinpath(client._slugify("Slowdive") + ".json").exists())

    def test_transient_errors_and_network_failures_are_not_cached(self):
        for payload, error in (({"error": 29}, None), ({"error": 11}, None), (None, OSError("down"))):
            tags, _ = self.get(payload, error)
            self.assertEqual(tags, [])
            self.assertEqual(list(Path(self.tmp.name).iterdir()), [])
        tags, _ = self.get(TAGS)                              # 나중에 다시 시도하면 정상 저장
        self.assertEqual(len(tags), 1)


class PendingTest(unittest.TestCase):
    def test_pending_artists_are_most_played_first_and_skip_cached_or_blank(self):
        df = pd.DataFrame({"artist": ["A"] * 5 + ["B"] * 3 + ["C"] * 9 + [""] * 4 + [None] * 2})
        with mock.patch.object(fat, "is_cached", side_effect=lambda n: n == "B"):
            self.assertEqual(fat.pending_artists(df), [("C", 9), ("A", 5)])


if __name__ == "__main__":
    unittest.main()
