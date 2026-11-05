"""새로고침 진행률(refresh_progress) 테스트. 실행:
    python3 -m unittest discover -s tests -v
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.refresh_progress import META_STEPS, STEPS, RefreshProgress  # noqa: E402


class RefreshProgressTest(unittest.TestCase):
    def test_idle_then_steps_increase(self):
        p = RefreshProgress()
        self.assertEqual(p.snapshot()["percent"], 0)
        self.assertFalse(p.snapshot()["running"])
        self.assertTrue(p.start())
        last = -1.0
        for key, _, _ in STEPS:
            p.begin(key)
            now = p.snapshot()["percent"]
            self.assertGreaterEqual(now, last)
            last = now
        p.finish()
        snap = p.snapshot()
        self.assertEqual((snap["percent"], snap["done"], snap["running"]), (100.0, True, False))

    def test_sub_progress_moves_inside_a_step(self):
        p = RefreshProgress()
        p.start()
        p.begin("fetch")
        p.sub(0, 10)
        a = p.snapshot()["percent"]
        p.sub(5, 10, "5/10 페이지")
        b = p.snapshot()
        p.sub(10, 10)
        c = p.snapshot()["percent"]
        self.assertLess(a, b["percent"])
        self.assertLess(b["percent"], c)
        self.assertEqual(b["detail"], "5/10 페이지")
        p.begin("preprocess")
        self.assertAlmostEqual(p.snapshot()["percent"], c, delta=0.1)       # 앞 단계가 끝난 지점부터 이어진다
        self.assertEqual(p.snapshot()["detail"], "")

    def test_cannot_start_twice_but_can_after_finish(self):
        p = RefreshProgress()
        self.assertTrue(p.start())
        self.assertFalse(p.start())
        p.finish()
        self.assertTrue(p.start())
        self.assertEqual(p.snapshot()["percent"], 0)            # 이전 실행의 완료 상태가 남지 않는다

    def test_zero_total_is_safe(self):
        p = RefreshProgress()
        p.start()
        p.begin("fetch")
        p.sub(3, 0)
        self.assertEqual(p.snapshot()["percent"], 0)


class MetaProgressTest(unittest.TestCase):
    """스크로블 묶음과 부가 정보(곡 길이·태그·연도) 묶음은 단계 목록만 다른 같은 진행률이다."""

    def test_scrobble_steps_come_first_and_metadata_is_separate(self):
        keys = [k for k, _, _ in STEPS]
        meta_keys = [k for k, _, _ in META_STEPS]
        self.assertEqual(keys, ["fetch", "preprocess", "artists", "titles"])      # 화면이 기다리는 묶음에는 부가 정보가 없다
        self.assertEqual(meta_keys, ["durations", "tags", "years"])
        self.assertFalse(set(keys) & set(meta_keys))

    def test_meta_steps_increase_to_100(self):
        p = RefreshProgress(META_STEPS)
        self.assertTrue(p.start())
        self.assertEqual(p.snapshot()["steps"], 3)
        last = -1.0
        for key, _, _ in META_STEPS:
            p.begin(key)
            now = p.snapshot()["percent"]
            self.assertGreaterEqual(now, last)
            last = now
        p.finish()
        self.assertEqual(p.snapshot()["percent"], 100.0)

    def test_result_is_kept_until_next_start(self):
        p = RefreshProgress(META_STEPS)
        p.start()
        p.set_result({"durations": {"found": 3}})
        p.finish()
        snap = p.snapshot()
        self.assertTrue(snap["done"])
        self.assertEqual(snap["result"], {"durations": {"found": 3}})
        self.assertIsNotNone(snap["ended_at"])                    # 화면이 "방금 끝난 결과"만 알릴 수 있게 끝난 시각을 준다
        self.assertLess(snap["ended_ago"], 5)
        self.assertTrue(p.start())
        self.assertIsNone(p.snapshot()["result"])                 # 새 실행에는 이전 결과가 남지 않는다
        self.assertIsNone(p.snapshot()["ended_at"])


class RunMetadataTest(unittest.TestCase):
    def setUp(self):
        from app import main
        self.main = main
        self._orig = main._fill_metadata

    def tearDown(self):
        self.main._fill_metadata = self._orig
        self.main.meta_progress.finish()

    def test_result_is_stored_and_progress_finishes(self):
        self.main._fill_metadata = lambda script: {"durations": {"found": 2}, "tags": None, "album_years": {"started": True}}
        self.assertTrue(self.main.meta_progress.start())
        self.main._run_metadata(Path("/tmp"))
        snap = self.main.meta_progress.snapshot()
        self.assertTrue(snap["done"] and not snap["running"])
        self.assertEqual(snap["result"]["durations"], {"found": 2})

    def test_exception_still_finishes_with_error(self):
        def boom(script):
            raise RuntimeError("조회 실패")

        self.main._fill_metadata = boom
        self.assertTrue(self.main.meta_progress.start())
        self.main._run_metadata(Path("/tmp"))
        snap = self.main.meta_progress.snapshot()
        self.assertTrue(snap["done"] and not snap["running"])        # 실패해도 "채우는 중"으로 영원히 남지 않는다
        self.assertIn("조회 실패", snap["result"]["error"])


class RunFetchTest(unittest.TestCase):
    def setUp(self):
        from app import main
        self.main = main
        main.refresh_progress.start()
        main.refresh_progress.begin("fetch")

    def tearDown(self):
        self.main.refresh_progress.finish()

    def test_progress_lines_on_stderr_update_progress(self):
        code = "import sys; print('out line'); [print(f'[progress] {i}/4', file=sys.stderr, flush=True) for i in (1, 2, 3, 4)]"
        res = self.main._run_fetch([sys.executable, "-c", code], 20)
        self.assertEqual(res.returncode, 0)
        self.assertIn("out line", res.stdout)
        snap = self.main.refresh_progress.snapshot()
        self.assertEqual(snap["detail"], "4/4 페이지")

    def test_failure_keeps_stderr(self):
        res = self.main._run_fetch([sys.executable, "-c", "import sys; print('boom', file=sys.stderr); sys.exit(3)"], 20)
        self.assertEqual(res.returncode, 3)
        self.assertIn("boom", res.stderr)

    def test_timeout(self):
        with self.assertRaises(subprocess.TimeoutExpired):
            self.main._run_fetch([sys.executable, "-c", "import time; time.sleep(30)"], 1)


if __name__ == "__main__":
    unittest.main()
