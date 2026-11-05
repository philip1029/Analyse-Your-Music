"""새로고침 진행률(refresh_progress) 테스트. 실행:
    python3 -m unittest discover -s tests -v
"""

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.refresh_progress import STEPS, RefreshProgress  # noqa: E402


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
