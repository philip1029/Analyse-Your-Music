"""앨범 발매연도 조회·연대 집계 규칙 테스트 (가짜 MusicBrainz 객체 사용, 네트워크 없음). 실행:
    python3 -m unittest discover -s tests -v
"""

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import album_years as ay  # noqa: E402
from app.analysis.decades import build_decades  # noqa: E402


def hit(title, artist, year):
    return {"title": title, "credits": [artist], "year": year}


class FakeMb:
    """results: {(artist, 검색 제목): [hit...]}, errors: 일시적 오류를 낼 (artist, 검색 제목) 집합."""

    def __init__(self, results=None, errors=()):
        self.results, self.errors = results or {}, set(errors)
        self.calls = []

    def search(self, artist, album):
        self.calls.append((artist, album))
        if (artist, album) in self.errors:
            return "error", []
        return "ok", self.results.get((artist, album), [])


def apple(*albums):
    """(artist, album, year) -> AppleYears"""
    return ay.AppleYears([{"Artist": a, "Album": b, "Track Year": y} for a, b, y in albums])


class AlbumVariantsTest(unittest.TestCase):
    def test_strips_reissue_tags(self):
        self.assertEqual(ay.album_variants("Abbey Road (2019 Mix)"), ["Abbey Road (2019 Mix)", "Abbey Road"])
        self.assertEqual(ay.album_variants("Meddle (2016 Remaster)")[1], "Meddle")
        self.assertEqual(ay.album_variants("Red (2024 Elemental Mixes)")[1], "Red")
        self.assertEqual(ay.album_variants("The Dark Side of the Moon (50th Anniversary) [Remastered]")[1], "The Dark Side of the Moon")
        self.assertEqual(ay.album_variants("Rubber Soul - Deluxe Edition")[1], "Rubber Soul")

    def test_strips_format_suffix(self):
        self.assertEqual(ay.album_variants("사랑으로 - EP")[1], "사랑으로")
        self.assertEqual(ay.album_variants("Hello - Single")[1], "Hello")

    def test_keeps_titles_that_change_the_record(self):
        self.assertEqual(ay.album_variants("Unplugged (Live)"), ["Unplugged (Live)"])
        self.assertEqual(ay.album_variants("Currents"), ["Currents"])


class OverridesTest(unittest.TestCase):
    def write(self, text):
        d = tempfile.mkdtemp()
        p = Path(d) / "album_years.txt"
        p.write_text(text, encoding="utf-8")
        return p

    def test_parse(self):
        p = self.write("# 설명\n\nWeezer :: Weezer -> 1994\n* :: Abbey Road -> 1969\n잘못된 줄\nA :: B -> abc\nA :: C -> 1800\n")
        o = ay.load_overrides(p)
        self.assertEqual(ay.override_for(o, "weezer", "WEEZER"), 1994)
        self.assertEqual(ay.override_for(o, "The Beatles", "Abbey Road"), 1969)       # * 는 앨범 이름만으로
        self.assertIsNone(ay.override_for(o, "A", "B"))                              # 연도가 숫자가 아님
        self.assertIsNone(ay.override_for(o, "A", "C"))                              # 범위 밖 연도
        self.assertEqual(len(o), 2)

    def test_missing_file_is_empty(self):
        self.assertEqual(ay.load_overrides(Path(tempfile.mkdtemp()) / "none.txt"), {})

    def test_repo_file_parses(self):
        self.assertIsInstance(ay.load_overrides(), dict)


class AppleYearsTest(unittest.TestCase):
    def test_pair_lookup_is_normalized(self):
        a = apple(("The Beatles", "Abbey Road", 1969))
        self.assertEqual(a.get("the beatles", "ABBEY ROAD"), 1969)

    def test_variant_title(self):
        a = apple(("Pink Floyd", "Meddle", 1971))
        self.assertEqual(a.get("Pink Floyd", "Meddle (2016 Remaster)"), 1971)

    def test_most_common_year_then_earliest_on_tie(self):
        a = apple(("X", "Y", 2001), ("X", "Y", 2001), ("X", "Y", 1999))
        self.assertEqual(a.get("X", "Y"), 2001)
        b = apple(("X", "Y", 2001), ("X", "Y", 1999))
        self.assertEqual(b.get("X", "Y"), 1999)

    def test_album_only_lookup_needs_one_year(self):
        a = apple(("Artist A", "Unique Album", 2010), ("Artist B", "Same Name", 1990), ("Artist C", "Same Name", 2005))
        self.assertEqual(a.get("Other Spelling", "Unique Album"), 2010)
        self.assertIsNone(a.get("Other Spelling", "Same Name"))

    def test_release_date_fallback_and_invalid_years(self):
        a = ay.AppleYears([{"Artist": "A", "Album": "B", "Release Date": "1995-03-01T00:00:00Z"}, {"Artist": "A", "Album": "C", "Track Year": 0}])
        self.assertEqual(a.get("A", "B"), 1995)
        self.assertIsNone(a.get("A", "C"))

    def test_load_from_zip_and_missing(self):
        d = Path(tempfile.mkdtemp())
        with zipfile.ZipFile(d / "Apple Music Library Tracks.json.zip", "w") as z:
            z.writestr("Apple Music Library Tracks.json", json.dumps([{"Artist": "A", "Album": "B", "Track Year": 1980}]))
        self.assertEqual(ay.load_apple_years(d).get("A", "B"), 1980)
        self.assertIsNone(ay.load_apple_years(Path(tempfile.mkdtemp())))
        self.assertIsNone(ay.load_apple_years(None))


class MbMatchTest(unittest.TestCase):
    def test_title_and_artist_must_match(self):
        hits = [hit("Currents", "Tame Impala", 2015), hit("Currents", "Someone Else", 1990), hit("Other", "Tame Impala", 2000)]
        self.assertEqual(ay.mb_years(hits, "Tame Impala", "Currents"), {2015})

    def test_artist_containment_but_not_short_names(self):
        # 공동 크레딧 표기 차이(LIA & VISUAL ARTS / Key 와 VISUAL ARTS / Key)는 서로 포함이라 같은 아티스트로 본다
        self.assertEqual(ay.mb_years([hit("Air Original Soundtrack", "VISUAL ARTS / Key", 2002)], "LIA & VISUAL ARTS / Key", "Air Original Soundtrack"), {2002})
        self.assertEqual(ay.mb_years([hit("T", "Prince and The Revolution", 1984)], "Prince", "T"), {1984})
        self.assertEqual(ay.mb_years([hit("T", "Mika", 1984)], "Ik", "T"), set())     # 3글자 미만이면 포함 관계는 보지 않음


class ResolveYearTest(unittest.TestCase):
    def test_musicbrainz_wins_over_apple(self):
        mb = FakeMb({("Radiohead", "The Bends"): [hit("The Bends", "Radiohead", 1994)]})
        res = ay.resolve_year("Radiohead", "The Bends", mb, apple(("Radiohead", "The Bends", 1995)))
        self.assertEqual(res, {"year": 1994, "src": "musicbrainz"})

    def test_apple_fills_when_musicbrainz_has_nothing(self):
        res = ay.resolve_year("빈지노", "NOWITZKI", FakeMb(), apple(("빈지노", "NOWITZKI", 2023)))
        self.assertEqual(res, {"year": 2023, "src": "apple"})

    def test_stripped_title_is_tried_after_original(self):
        mb = FakeMb({("The Beatles", "Revolver"): [hit("Revolver", "The Beatles", 1966)]})
        res = ay.resolve_year("The Beatles", "Revolver (2022 Mix)", mb)
        self.assertEqual(res["year"], 1966)
        self.assertEqual(mb.calls, [("The Beatles", "Revolver (2022 Mix)"), ("The Beatles", "Revolver")])

    def test_multiple_years_prefer_apple_when_it_is_a_candidate(self):
        mb = FakeMb({("Weezer", "Weezer"): [hit("Weezer", "Weezer", 1994), hit("Weezer", "Weezer", 2001)]})
        res = ay.resolve_year("Weezer", "Weezer", mb, apple(("Weezer", "Weezer", 1994)))
        self.assertEqual(res, {"year": 1994, "src": "musicbrainz:apple"})

    def test_multiple_years_without_apple_take_earliest_and_flag_ambiguous(self):
        mb = FakeMb({("Weezer", "Weezer"): [hit("Weezer", "Weezer", 2001), hit("Weezer", "Weezer", 1994)]})
        res = ay.resolve_year("Weezer", "Weezer", mb)
        self.assertEqual(res, {"year": 1994, "src": "musicbrainz", "ambiguous": [1994, 2001]})

    def test_not_found_anywhere(self):
        self.assertEqual(ay.resolve_year("A", "B", FakeMb(), apple()), {"year": None, "src": None})

    def test_transient_error_without_apple_is_not_decided(self):
        self.assertIsNone(ay.resolve_year("A", "B", FakeMb(errors={("A", "B")})))

    def test_transient_error_with_apple_keeps_apple_year_but_retries_later(self):
        res = ay.resolve_year("A", "B", FakeMb(errors={("A", "B")}), apple(("A", "B", 2000)))
        self.assertEqual(res, {"year": 2000, "src": "apple", "retry": True})

    def test_apple_only_mode(self):
        self.assertEqual(ay.resolve_year("A", "B", None, apple(("A", "B", 1977))), {"year": 1977, "src": "apple"})
        self.assertEqual(ay.resolve_year("A", "B", None, None), {"year": None, "src": None})


class NeedsLookupTest(unittest.TestCase):
    def test_rules(self):
        now = 10_000_000
        self.assertTrue(ay.needs_lookup(None, now))
        self.assertFalse(ay.needs_lookup({"year": 1990, "tried": now}, now))
        self.assertTrue(ay.needs_lookup({"year": 1990, "retry": True, "tried": now}, now))
        self.assertFalse(ay.needs_lookup({"year": None, "tried": now - 86400}, now))                 # 방금 못 찾음: 아직 안 함
        self.assertTrue(ay.needs_lookup({"year": None, "tried": now - 31 * 86400}, now))             # 30일 지남


class FillYearsTest(unittest.TestCase):
    def test_limit_order_and_overrides(self):
        pairs = [("A", "one", 50), ("B", "two", 40), ("C", "three", 30), ("D", "four", 20)]
        mb = FakeMb({(a, t): [hit(t, a, 2000 + i)] for i, (a, t, _) in enumerate(pairs)})
        cache = {ay.cache_key("B", "two"): {"year": None, "src": None, "tried": 0}}   # 예전에 못 찾음 → 재시도 대상이라 새 앨범보다 뒤
        overrides = {(ay.norm("C"), ay.norm("three")): 1999}                             # 수동 보정은 조회하지 않음
        stats = ay.fill_years(pairs, cache, mb, None, overrides, limit=2, now=40 * 86400)
        self.assertEqual([c[1] for c in mb.calls], ["one", "four"])
        self.assertEqual(stats, {"found": 2, "unknown": 0, "skipped": 0, "remaining": 1, "stopped": False})
        self.assertEqual(cache[ay.cache_key("A", "one")]["year"], 2000)
        self.assertNotIn(ay.cache_key("C", "three"), cache)

    def test_transient_errors_are_not_cached_and_stop_the_run(self):
        pairs = [(f"A{i}", "x", 10 - i) for i in range(6)]
        mb = FakeMb(errors={(a, "x") for a, _, _ in pairs})
        cache = {}
        stats = ay.fill_years(pairs, cache, mb)
        self.assertEqual(cache, {})
        self.assertEqual(stats["skipped"], ay.MAX_TRANSIENT_RUN)
        self.assertTrue(stats["stopped"])
        self.assertEqual(len(mb.calls), ay.MAX_TRANSIENT_RUN)
        self.assertEqual(stats["remaining"], 6 - ay.MAX_TRANSIENT_RUN)

    def test_nothing_to_do(self):
        cache = {ay.cache_key("A", "B"): {"year": 1990, "src": "apple", "tried": 1}}
        self.assertEqual(ay.fill_years([("A", "B", 5)], cache, FakeMb())["remaining"], 0)


class MusicBrainzClientTest(unittest.TestCase):
    class Resp:
        def __init__(self, status, payload=None):
            self.status_code, self.payload = status, payload

        def json(self):
            return self.payload

    class Session:
        def __init__(self, *responses):
            self.responses, self.params = list(responses), []

        def get(self, url, params=None, headers=None, timeout=None):
            self.params.append(params)
            r = self.responses.pop(0)
            if isinstance(r, Exception):
                raise r
            return r

    def client(self, *responses):
        return ay.MusicBrainzClient(gap=0, session=self.Session(*responses))

    def test_parses_hits_and_quotes_query(self):
        body = {"release-groups": [
            {"title": "Currents", "first-release-date": "2015-07-17", "artist-credit": [{"name": "Tame Impala", "joinphrase": "", "artist": {"name": "Tame Impala"}}]},
            {"title": "No Date", "first-release-date": "", "artist-credit": []},
        ]}
        c = self.client(self.Resp(200, body))
        with mock.patch("time.sleep"):
            st, hits = c.search('Say "Hi"', "Currents")
        self.assertEqual(st, "ok")
        self.assertEqual(hits, [{"title": "Currents", "credits": ["Tame Impala"], "year": 2015}])
        self.assertIn('artist:"Say \\"Hi\\""', c.session.params[0]["query"])

    def test_retries_503_then_succeeds(self):
        c = self.client(self.Resp(503), self.Resp(200, {"release-groups": []}))
        with mock.patch("time.sleep"):
            self.assertEqual(c.search("A", "B"), ("ok", []))
        self.assertEqual(c.calls, 2)

    def test_gives_up_after_repeated_errors(self):
        c = self.client(self.Resp(503), self.Resp(503), self.Resp(503), self.Resp(503))
        with mock.patch("time.sleep"):
            self.assertEqual(c.search("A", "B"), ("error", []))

    def test_network_exception_is_transient(self):
        import requests

        c = self.client(*[requests.ConnectionError("down")] * 4)
        with mock.patch("time.sleep"):
            self.assertEqual(c.search("A", "B"), ("error", []))

    def test_bad_query_is_not_a_transient_error(self):
        c = self.client(self.Resp(400))
        with mock.patch("time.sleep"):
            self.assertEqual(c.search("A", "B"), ("ok", []))


class LookupTest(unittest.TestCase):
    def test_override_beats_cache_and_files_reload(self):
        d = Path(tempfile.mkdtemp())
        cache_path, ov_path = d / ay.CACHE_NAME, d / "album_years.txt"
        lookup = ay.AlbumYearLookup(cache_path, ov_path)
        self.assertIsNone(lookup.get("A", "B"))                                         # 파일이 없으면 조회 전
        ay.save_cache(cache_path, {ay.cache_key("A", "B"): {"year": 1990, "src": "musicbrainz", "tried": 1}})
        self.assertEqual(lookup.get("A", "B")["year"], 1990)
        ov_path.write_text("a :: b -> 1985\n", encoding="utf-8")
        self.assertEqual(lookup.get("A", "B"), {"year": 1985, "src": "manual"})


class FakeLookup:
    def __init__(self, table):
        self.table = table

    def get(self, artist, album):
        return self.table.get((artist, album))


def scrobbles(rows):
    """rows: [(artist, album, 횟수)]"""
    out = []
    for artist, album, n in rows:
        out += [{"uts": len(out) + i, "utc_time": "2024-01-01 00:00:00", "artist": artist, "album": album, "track": f"{album} t{i}", "source": "L"} for i in range(n)]
    return pd.DataFrame(out)


class BuildDecadesTest(unittest.TestCase):
    def test_distribution_coverage_and_extremes(self):
        df = scrobbles([("A", "Old", 5), ("A", "Mid", 3), ("B", "New", 2), ("C", "Unknown", 4), ("D", "Pending", 1)])
        lookup = FakeLookup({
            ("A", "Old"): {"year": 1969, "src": "musicbrainz"},
            ("A", "Mid"): {"year": 1994, "src": "apple"},
            ("B", "New"): {"year": 2023, "src": "manual"},
            ("C", "Unknown"): {"year": None, "src": None},
        })
        r = build_decades(df, lookup)
        self.assertEqual([d["decade"] for d in r["decades"]], [1960, 1970, 1980, 1990, 2000, 2010, 2020])    # 빈 연대도 이어서 보여 준다
        by = {d["decade"]: d for d in r["decades"]}
        self.assertEqual((by[1960]["plays"], by[1960]["albums"], by[1960]["artists"]), (5, 1, 1))
        self.assertEqual(by[1970]["plays"], 0)
        self.assertEqual(by[1960]["top"][0], {"artist": "A", "album": "Old", "year": 1969, "plays": 5})
        self.assertEqual(r["coverage"]["known_plays"], 10)
        self.assertEqual(r["coverage"]["total_plays"], 15)
        self.assertAlmostEqual(r["coverage"]["pct"], 0.6667, places=3)
        self.assertEqual((r["coverage"]["albums_unchecked"], r["coverage"]["albums_not_found"]), (1, 1))
        self.assertFalse(r["reliable"])
        self.assertEqual(r["oldest"], {"artist": "A", "album": "Old", "year": 1969})
        self.assertEqual(r["newest"], {"artist": "B", "album": "New", "year": 2023})
        self.assertEqual(r["sources"], {"musicbrainz": 1, "apple": 1, "manual": 1})
        self.assertEqual([u["album"] for u in r["unknown_top"]], ["Unknown", "Pending"])

    def test_reliable_when_coverage_is_high(self):
        df = scrobbles([("A", "X", 9), ("B", "Y", 1)])
        r = build_decades(df, FakeLookup({("A", "X"): {"year": 2001, "src": "apple"}}))
        self.assertTrue(r["reliable"])
        self.assertEqual(r["coverage"]["pct"], 0.9)

    def test_ambiguous_count(self):
        df = scrobbles([("A", "X", 2)])
        r = build_decades(df, FakeLookup({("A", "X"): {"year": 1994, "src": "musicbrainz", "ambiguous": [1994, 2001]}}))
        self.assertEqual(r["ambiguous_albums"], 1)

    def test_empty_and_all_unknown(self):
        r = build_decades(scrobbles([]).reindex(columns=["uts", "utc_time", "artist", "album", "track", "source"]), FakeLookup({}))
        self.assertEqual(r["decades"], [])
        self.assertFalse(r["reliable"])
        r = build_decades(scrobbles([("A", "X", 3)]), FakeLookup({}))
        self.assertEqual(r["decades"], [])
        self.assertEqual(r["coverage"]["pct"], 0.0)
        self.assertEqual(r["unknown_top"][0]["album"], "X")


if __name__ == "__main__":
    unittest.main()
