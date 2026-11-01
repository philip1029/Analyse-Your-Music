"""Apple 로그로 빠진 청취 기록 채우기 규칙 테스트 (합성 데이터, 파일·네트워크 없음). 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "backend"))

import fill_apple_gaps as g  # noqa: E402

T0 = int(datetime(2026, 10, 1, 12, 0, 0, tzinfo=timezone.utc).timestamp())


def row(uts, artist, album, track, source="L"):
    return {"uts": str(uts), "utc_time": "", "artist": artist, "album": album, "track": track, "source": source}


def session(uts, track, album="Al", play_s=200, media_s=200):
    return {"uts": uts, "track": track, "album": album, "play_s": play_s, "media_s": media_s}


def seg(start_s, play_ms=200000, media_ms=200000, startpos=0, endpos=None):
    st = datetime.fromtimestamp(start_s, timezone.utc)
    return {"st": st, "et": st + timedelta(milliseconds=play_ms), "play_ms": play_ms, "media_ms": media_ms, "startpos": startpos, "endpos": play_ms if endpos is None else endpos}


class BuildSessionsTest(unittest.TestCase):
    def test_threshold_and_merge(self):
        groups = {
            ("Full", "Al"): [seg(T0, 200000, 200000)],                                   # 100% -> 세션
            ("Half", "Al"): [seg(T0, 100000, 200000)],                                   # 정확히 50% -> 세션
            ("Short", "Al"): [seg(T0, 60000, 200000)],                                   # 30% -> 제외
            ("Long", "Al"): [seg(T0, 240000, 900000)],                                   # 240초 이상 -> 세션
            ("Split", "Al"): [seg(T0, 60000, 200000, 0, 60000), seg(T0 + 61, 60000, 200000, 60000, 120000)],   # 이어진 조각 -> 한 세션(120초=60%)
            ("NoMedia", "Al"): [seg(T0, 200000, 0)],                                     # 곡 길이를 모르면 제외
        }
        names = sorted(s["track"] for s in g.build_sessions_all(groups))
        self.assertEqual(names, ["Full", "Half", "Long", "Split"])
        split = next(s for s in g.build_sessions_all(groups) if s["track"] == "Split")
        self.assertEqual(split["play_s"], 120)


class ResolverTest(unittest.TestCase):
    def test_csv_spelling_first_then_apple_then_unique_track(self):
        rows = [row(T0, "Pink Floyd", "The Wall", "Hey You"), row(T0 + 1, "Pink Floyd", "The Wall", "Hey You"), row(T0 + 2, "Other", "The Wall", "Hey You"),
                row(T0 + 3, "Solo", "Odd Album", "Unique Song")]
        apple = lambda t, a: ("From Apple", a) if t == "Only Apple" else ("", a)   # noqa: E731
        r = g.make_resolver(rows, apple)
        self.assertEqual(r("hey you", "THE WALL"), ("Pink Floyd", "The Wall"))        # CSV 표기(가장 많은 쪽)를 쓴다
        self.assertEqual(r("Only Apple", "X"), ("From Apple", "X"))
        self.assertEqual(r("Unique Song", "Different Album"), ("Solo", "Different Album"))   # 곡명이 한 아티스트에만 대응
        self.assertEqual(r("Hey You", "Different Album"), ("", "Different Album"))           # 여러 아티스트면 추측하지 않는다
        self.assertEqual(g.make_resolver(rows)("Nothing", ""), ("", ""))


class FindGapRowsTest(unittest.TestCase):
    def run_rule(self, sessions, rows, **kw):
        return g.find_gap_rows(sessions, rows, resolve=kw.pop("resolve", lambda t, a: ("Art", a)), **kw)

    def test_plain_gap_is_filled(self):
        found, skipped = self.run_rule([session(T0, "Lost")], [row(T0 - 3600, "Z", "Other", "Far")])
        self.assertEqual([(f["track"], f["artist"], f["uts"]) for f in found], [("Lost", "Art", T0)])
        self.assertEqual(sum(skipped.values()), 0)

    def test_already_recorded_same_track(self):
        found, skipped = self.run_rule([session(T0, "Song")], [row(T0 + 30, "Art", "Al", "SONG")])
        self.assertEqual((found, dict(skipped)), ([], {"covered_track": 1}))
        # 창 밖(15분 넘게 뒤)에 있는 같은 곡 기록은 같은 재생이 아니다
        found, _ = self.run_rule([session(T0, "Song")], [row(T0 + AFTER_PLUS, "Art", "Al", "Song")])
        self.assertEqual(len(found), 1)

    def test_same_album_nearby_means_title_spelling_differs(self):
        found, skipped = self.run_rule([session(T0, "Come Together (2019 Mix)", "Abbey Road")], [row(T0 + 60, "Art", "Abbey Road", "Come Together")])
        self.assertEqual((found, dict(skipped)), ([], {"covered_album": 1}))

    def test_previously_removed_fake(self):
        found, skipped = self.run_rule([session(T0, "Fake")], [row(T0 - 7200, "Z", "Q", "Far")], removed=[row(T0 + 5, "Art", "Al", "Fake")])
        self.assertEqual((found, dict(skipped)), ([], {"previously_removed": 1}))

    def test_overlap_with_other_track_during_playback(self):
        found, skipped = self.run_rule([session(T0, "Slow", play_s=300, media_s=300)], [row(T0 + 120, "Z", "Q", "Other")])
        self.assertEqual((found, dict(skipped)), ([], {"overlap": 1}))
        # 재생이 끝난 뒤에 기록된 다음 곡은 겹침이 아니다
        found, _ = self.run_rule([session(T0, "Slow", play_s=300, media_s=300)], [row(T0 + 400, "Z", "Q", "Next")])
        self.assertEqual(len(found), 1)

    def test_no_artist_and_range(self):
        found, skipped = g.find_gap_rows([session(T0, "Who")], [], resolve=lambda t, a: ("", a))
        self.assertEqual((found, dict(skipped)), ([], {"no_artist": 1}))
        found, skipped = self.run_rule([session(T0 - 10, "Old"), session(T0 + 10, "In"), session(T0 + 5000, "Late")], [], since=T0, until=T0 + 100)
        self.assertEqual([f["track"] for f in found], ["In"])
        self.assertEqual(skipped["out_of_range"], 2)

    def test_same_play_logged_twice_with_different_album_is_added_once(self):
        found, skipped = self.run_rule([session(T0, "Vrioon", "Vrioon"), session(T0, "Vrioon", "Vrioon (Deluxe)")], [])
        self.assertEqual(len(found), 1)
        self.assertEqual(skipped["duplicate_session"], 1)

    def test_rule_order_counts_each_session_once(self):
        # 같은 곡이 이미 있으면서 같은 앨범도 있어도 covered_track 하나로만 센다
        found, skipped = self.run_rule([session(T0, "Song", "Al")], [row(T0, "Art", "Al", "Song")])
        self.assertEqual(dict(skipped), {"covered_track": 1})


AFTER_PLUS = g.AFTER + 60


class IndexTest(unittest.TestCase):
    def test_window_edges(self):
        idx = g._Index([("k", 1000)])
        self.assertTrue(idx.near("k", 1000 + g.BEFORE, g.BEFORE, g.AFTER))       # 시작 -10분 경계
        self.assertFalse(idx.near("k", 1000 + g.BEFORE + 1, g.BEFORE, g.AFTER))
        self.assertTrue(idx.near("k", 1000 - g.AFTER, g.BEFORE, g.AFTER))        # 시작 +15분 경계
        self.assertFalse(idx.near("k", 1000 - g.AFTER - 1, g.BEFORE, g.AFTER))
        self.assertFalse(idx.near("missing", 1000, g.BEFORE, g.AFTER))


if __name__ == "__main__":
    unittest.main()
