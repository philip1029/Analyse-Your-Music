"""곡 길이 조회 규칙 테스트 (가짜 Last.fm 객체 사용, 네트워크 없음). 실행:
    python3 -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.lastfm import durations as d  # noqa: E402


class FakeLastFm:
    """info: {(artist, track): 초}, search_results: [(artist, track)], errors: getInfo 가 일시적 오류를 낼 (artist, track) 집합."""

    def __init__(self, info=None, search_results=(), errors=()):
        self.info, self.search_results, self.errors = info or {}, list(search_results), set(errors)
        self.calls = []

    def get_duration(self, artist, track):
        self.calls.append(("info", artist, track))
        if (artist, track) in self.errors:
            return "error", 0
        return "ok", self.info.get((artist, track), 0)

    def search(self, artist, track):
        self.calls.append(("search", artist, track))
        return "ok", self.search_results


def apple(*tracks):
    return d.AppleDurations([{"Title": t, "Artist": a, "Track Duration": ms} for a, t, ms in tracks])


class TitleVariantsTest(unittest.TestCase):
    def test_strips_length_neutral_tags_only(self):
        self.assertEqual(d.title_variants("Come Together (2019 Mix)"), ["Come Together (2019 Mix)"])      # Mix 는 길이가 달라질 수 있어 유지
        self.assertEqual(d.title_variants("Money (2011 Remaster)"), ["Money (2011 Remaster)", "Money"])
        self.assertEqual(d.title_variants("Money - Remastered 2011"), ["Money - Remastered 2011", "Money"])
        self.assertEqual(d.title_variants("Song [Mono] (feat. X)"), ["Song [Mono] (feat. X)", "Song"])

    def test_live_remix_and_edit_are_kept(self):
        for t in ("Song (Live)", "Song (Remix)", "Song (Radio Edit)", "Song - Live at Budokan"):
            self.assertEqual(d.title_variants(t), [t])

    def test_title_without_tags_has_one_variant(self):
        self.assertEqual(d.title_variants("Plain Title"), ["Plain Title"])


class ResolveTest(unittest.TestCase):
    def test_apple_exact_match_is_used_first_without_network(self):
        fm = FakeLastFm()
        r = d.resolve_duration("Pink Floyd", "Money", fm, apple(("pink floyd", "MONEY", 382000)))
        self.assertEqual(r, {"sec": 382, "src": "apple"})
        self.assertEqual(fm.calls, [])

    def test_lastfm_exact_then_variant_then_search_then_apple_title(self):
        fm = FakeLastFm(info={("A", "Song"): 200})
        self.assertEqual(d.resolve_duration("A", "Song (2011 Remaster)", fm), {"sec": 200, "src": "lastfm:variant"})
        fm = FakeLastFm(info={("A", "Song"): 200})
        self.assertEqual(d.resolve_duration("A", "Song", fm), {"sec": 200, "src": "lastfm"})
        fm = FakeLastFm(info={("Artist Full", "Song"): 180}, search_results=[("Artist Full", "Song")])
        self.assertEqual(d.resolve_duration("Artist", "Song", fm), {"sec": 180, "src": "lastfm:search"})
        fm = FakeLastFm()
        self.assertEqual(d.resolve_duration("뉴진스", "Super Shy", fm, apple(("NewJeans", "Super Shy", 155000))), {"sec": 155, "src": "apple:title"})

    def test_search_hit_with_other_title_or_unrelated_artist_is_rejected(self):
        fm = FakeLastFm(info={("Other", "Song"): 100, ("A", "Song 2"): 100}, search_results=[("Other", "Song"), ("A", "Song 2")])
        self.assertEqual(d.resolve_duration("A", "Song", fm), {"sec": None, "src": None})

    def test_title_only_apple_match_requires_a_single_duration(self):
        ap = apple(("X", "Intro", 30000), ("Y", "Intro", 95000))
        self.assertIsNone(ap.get_title("Z", "Intro"))
        self.assertEqual(apple(("X", "Intro", 30000), ("Y", "Intro", 31000)).get_title("Z", "Intro"), 30)

    def test_transient_error_without_result_is_not_cacheable(self):
        fm = FakeLastFm(errors={("A", "Song")})
        self.assertIsNone(d.resolve_duration("A", "Song", fm))

    def test_transient_error_but_found_elsewhere_is_returned(self):
        fm = FakeLastFm(errors={("A", "Song")})
        self.assertEqual(d.resolve_duration("A", "Song", fm, apple(("A", "Song", 100000)))["sec"], 100)

    def test_not_found_is_a_cacheable_unknown(self):
        self.assertEqual(d.resolve_duration("A", "Song", FakeLastFm()), {"sec": None, "src": None})

    def test_search_can_be_disabled(self):
        fm = FakeLastFm(search_results=[("A", "Song")])
        d.resolve_duration("A", "Song", fm, use_search=False)
        self.assertNotIn("search", [c[0] for c in fm.calls])


class CacheAndLookupTest(unittest.TestCase):
    def test_needs_lookup_rules(self):
        self.assertTrue(d.needs_lookup(None))
        self.assertFalse(d.needs_lookup({"sec": 200, "tried": 0}))
        self.assertFalse(d.needs_lookup({"sec": None, "tried": 1000}, now=1000 + 86400))
        self.assertTrue(d.needs_lookup({"sec": None, "tried": 1000}, now=1000 + 31 * 86400))

    def test_cache_roundtrip_and_lookup_with_spelling_tolerance(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / d.CACHE_NAME
            self.assertEqual(d.load_cache(p), {})
            d.save_cache(p, {d.cache_key("Pink Floyd", "Money"): {"sec": 382, "src": "apple", "tried": 1},
                             d.cache_key("X", "Unknown"): {"sec": None, "src": None, "tried": 1}})
            lk = d.DurationLookup(p)
            self.assertEqual(lk.get("pink  floyd", "MONEY"), 382)
            self.assertIsNone(lk.get("X", "Unknown"))
            self.assertEqual(lk.get("Floyd Tribute", "Money"), 382)          # 아티스트 표기가 달라도 곡명 길이가 하나뿐이면 사용
            self.assertIsNone(d.DurationLookup(Path(tmp) / "missing.json").get("A", "B"))

    def test_load_apple_durations_from_zip_json_and_missing(self):
        tracks = [{"Title": "Money", "Artist": "Pink Floyd", "Track Duration": 382000}]
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(d.load_apple_durations(tmp))
            self.assertIsNone(d.load_apple_durations(None))
            with zipfile.ZipFile(Path(tmp) / "Apple Music Library Tracks.json.zip", "w") as z:
                z.writestr("Apple Music Library Tracks.json", json.dumps(tracks))
            self.assertEqual(d.load_apple_durations(tmp).get_pair("pink floyd", "money"), 382)


if __name__ == "__main__":
    unittest.main()
