"""공유 리포트 카드 데이터와 이미지 프록시 테스트 (합성 데이터, 네트워크 없음). 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis import library as lib  # noqa: E402
from app.analysis import listening_time as lt  # noqa: E402
from app.analysis import report_card as rc  # noqa: E402
from app.lastfm import durations as d  # noqa: E402
from app.lastfm import image_proxy as ip  # noqa: E402


def frame():
    rows = []
    for day in range(1, 29):
        for month in (1, 2, 3):
            for i, (artist, album, track) in enumerate([("A", "Album A", "Song A"), ("B", "Album B", "Song B"), ("C", "Album C", "Song C")]):
                rows.append({"utc_time": f"2025-{month:02d}-{day:02d} {10 + i:02d}:00:00", "artist": artist, "album": album, "track": track, "source": "L"})
    return pd.DataFrame(rows)


class ReportCardTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        path = Path(self.tmp.name) / d.CACHE_NAME
        d.save_cache(path, {d.cache_key("A", "Song A"): {"sec": 600, "src": "apple", "tried": 1}})
        lookup = d.DurationLookup(path)
        self.patches = [mock.patch.object(lt, "durations", lookup), mock.patch.object(lib, "durations", lookup)]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        self.tmp.cleanup()

    def test_month_card_numbers(self):
        r = rc.build_report_card(frame(), "month", "2025-02", "me")
        self.assertEqual((r["username"], r["label"], r["scrobbles"]), ("me", "2025년 2월", 28 * 3))
        self.assertEqual((r["artists"], r["albums"], r["tracks"]), (3, 3, 3))
        self.assertEqual((r["start"], r["end"]), ("2025-02-01", "2025-02-28"))
        self.assertEqual(r["seconds"], 28 * 600)                              # Song A 만 길이를 안다
        self.assertEqual(r["tops"]["artist"]["time"][0]["name"], "A")          # 시간 순위 1위
        self.assertEqual(len(r["tops"]["track"]["plays"]), 3)

    def test_all_card_covers_the_whole_data_range(self):
        r = rc.build_report_card(frame(), "all")
        self.assertEqual((r["label"], r["scrobbles"], r["start"], r["end"]), ("전체 기간", 28 * 9, "2025-01-01", "2025-03-28"))

    def test_hourly_arrays_and_busiest_day(self):
        r = rc.build_report_card(frame(), "all")
        self.assertEqual(len(r["hourly_plays"]), 24)
        self.assertEqual(r["hourly_plays"][19], 28 * 3)                          # UTC 10시 = KST 19시
        self.assertAlmostEqual(r["hourly_minutes"][19], 28 * 3 * 10)
        self.assertEqual(r["busiest_day"]["plays"], 3)

    def test_errors(self):
        with self.assertRaises(ValueError):
            rc.build_report_card(frame(), "decade")
        with self.assertRaises(ValueError):
            rc.build_report_card(frame(), "month", "2030-01")
        with self.assertRaises(ValueError):
            rc.build_report_card(frame().iloc[0:0], "all")


class FakeResp:
    def __init__(self, status=200, ctype="image/png", body=b"abc"):
        self.status_code, self.headers, self.body = status, {"content-type": ctype}, body

    def iter_content(self, n):
        yield self.body


class ImageProxyTest(unittest.TestCase):
    def test_allowlist(self):
        ok = ["https://lastfm-img.freetls.fastly.net/i/u/300x300/x.jpg", "https://cdn-images.dzcdn.net/images/artist/x/500x500.jpg"]
        bad = ["http://169.254.169.254/latest", "http://localhost:8000/api/health", "https://evil.example.com/a.png",
               "https://lastfm-img.freetls.fastly.net.evil.com/a.png", "https://user:pw@lastfm-img.freetls.fastly.net/a.png",
               "file:///etc/passwd", "ftp://lastfm-img.freetls.fastly.net/a.png", "notaurl", ""]
        self.assertTrue(all(ip.is_allowed(u) for u in ok))
        self.assertFalse(any(ip.is_allowed(u) for u in bad))

    def test_fetch_returns_bytes_and_type(self):
        with mock.patch.object(ip.requests, "get", return_value=FakeResp(body=b"PNGDATA")) as g:
            data, ctype = ip.fetch_image("https://lastfm-img.freetls.fastly.net/a.png")
        self.assertEqual((data, ctype), (b"PNGDATA", "image/png"))
        self.assertFalse(g.call_args.kwargs["allow_redirects"])                  # 리다이렉트로 허용 호스트를 벗어나지 못하게

    def test_rejects_disallowed_host_without_any_request(self):
        with mock.patch.object(ip.requests, "get") as g:
            with self.assertRaises(ValueError):
                ip.fetch_image("https://evil.example.com/a.png")
        g.assert_not_called()

    def test_rejects_non_image_svg_error_status_and_huge_files(self):
        url = "https://lastfm-img.freetls.fastly.net/a"
        for resp in (FakeResp(ctype="text/html"), FakeResp(ctype="image/svg+xml"), FakeResp(status=404), FakeResp(body=b"x" * (ip.MAX_BYTES + 1))):
            with mock.patch.object(ip.requests, "get", return_value=resp):
                with self.assertRaises(ValueError):
                    ip.fetch_image(url)


if __name__ == "__main__":
    unittest.main()
