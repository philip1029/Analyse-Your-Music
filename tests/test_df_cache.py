"""main._load_base_df (CSV 한 번만 읽고 재사용) 테스트. 임시 CSV 만 쓴다. 실행:
    python3 -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import main  # noqa: E402

HEADER = "uts,utc_time,artist,album,track,source\n"


class BaseDfCacheTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "me_scrobbles.csv"
        self.path.write_text(HEADER + "1,2026-01-01 00:00:00,A,Alb,Song,L\n2,2026-01-01 00:01:00,,,,A\n1,2026-01-01 00:00:00,A,Alb,Song,L\n", encoding="utf-8-sig")
        main._base_cache.update(sig=None, df=None)

    def tearDown(self):
        self.tmp.cleanup()
        main._base_cache.update(sig=None, df=None)

    def test_cleans_blanks_and_duplicates(self):
        df = main._load_base_df(self.path)
        self.assertEqual(len(df), 2)                                  # uts+artist+track 중복 제거
        self.assertEqual(list(df.loc[df["uts"] == 2, ["artist", "album", "track"]].iloc[0]), ["", "", ""])   # NaN 이 아니라 빈 문자열

    def test_returns_independent_copies_and_reads_file_once(self):
        a = main._load_base_df(self.path)
        sig = main._base_cache["sig"]
        base_obj = main._base_cache["df"]
        a["extra"] = 1                                                # 호출한 쪽이 열을 덧붙여도
        b = main._load_base_df(self.path)
        self.assertNotIn("extra", b.columns)                          # 다음 호출에는 영향이 없다
        self.assertIs(main._base_cache["df"], base_obj)               # 파일이 그대로면 다시 읽지 않는다
        self.assertEqual(main._base_cache["sig"], sig)

    def test_reloads_when_file_changes(self):
        main._load_base_df(self.path)
        time.sleep(0.01)
        self.path.write_text(HEADER + "9,2026-02-01 00:00:00,B,Alb,Other,L\n", encoding="utf-8-sig")
        os.utime(self.path, None)
        df = main._load_base_df(self.path)
        self.assertEqual(list(df["track"]), ["Other"])


if __name__ == "__main__":
    unittest.main()
