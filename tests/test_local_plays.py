"""fill_local_plays (로컬 파일 재생을 라이브러리 XML 로 채우기) 테스트. 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

import fill_local_plays as flp  # noqa: E402

SINCE = int(datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp())
NOW = int(datetime(2026, 11, 1, tzinfo=timezone.utc).timestamp())


def dt(y, m, d, h=0):
    return datetime(y, m, d, h)      # plist 날짜처럼 tz 없는 UTC


def track(name, artist="VA", album="Alb", count=3, last=dt(2026, 8, 21, 16), added=dt(2026, 7, 22), ms=200_000, kind="File"):
    return {"Name": name, "Artist": artist, "Album": album, "Track Type": kind, "Play Count": count, "Play Date UTC": last, "Date Added": added, "Total Time": ms}


class LocalPlaysTest(unittest.TestCase):
    def plan(self, tracks, rows=(), **kw):
        return flp.plan_local_plays(tracks, list(rows), since=kw.pop("since", SINCE), now=NOW, **kw)

    def test_last_play_is_exact_and_rest_is_estimated_backwards(self):
        plan, skipped, dropped = self.plan([track("Song", count=3)])
        self.assertEqual([p["estimated"] for p in plan], [0, 1, 1])
        last = int(datetime(2026, 8, 21, 16, tzinfo=timezone.utc).timestamp())
        self.assertEqual([p["uts"] for p in plan], [last, last - 230, last - 460])      # 곡 길이 200초 + 30초
        self.assertEqual(dropped, 0)

    def test_exact_only(self):
        plan, _, _ = self.plan([track("Song", count=5)], exact_only=True)
        self.assertEqual(len(plan), 1)

    def test_catalog_tracks_and_unplayed_are_skipped(self):
        plan, skipped, _ = self.plan([track("A", kind="Remote"), track("B", count=0), track("C", last=None)])
        self.assertEqual(plan, [])
        self.assertEqual(skipped["not_local"], 3)

    def test_already_recorded_by_artist_or_album(self):
        rows = [{"track": "Song", "artist": "VA", "album": "Other"}, {"track": "Tune", "artist": "X", "album": "Alb"}]
        plan, skipped, _ = self.plan([track("Song"), track("Tune"), track("New")], rows)
        self.assertEqual({p["track"] for p in plan}, {"New"})
        self.assertEqual(skipped["already_recorded"], 2)

    def test_estimates_stop_at_date_added_and_report_dropped(self):
        # 추가 직후에 마지막으로 들은 곡: 앞으로 놓을 자리가 없어 실제 1회만 남는다
        plan, _, dropped = self.plan([track("Song", count=4, last=dt(2026, 7, 22, 1), added=dt(2026, 7, 22, 1))])
        self.assertEqual(len(plan), 1)
        self.assertEqual(dropped, 3)

    def test_before_range(self):
        plan, skipped, _ = self.plan([track("Old", last=dt(2023, 1, 1), added=dt(2022, 1, 1))])
        self.assertEqual(plan, [])
        self.assertEqual(skipped["before_range"], 1)

    def test_unknown_length_uses_default(self):
        plan, _, _ = self.plan([track("Song", count=2, ms=0)])
        self.assertEqual(plan[0]["uts"] - plan[1]["uts"], flp.DEFAULT_DURATION_S + flp.GAP_S)


if __name__ == "__main__":
    unittest.main()
