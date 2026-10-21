"""env_config (API 키·유저네임·Apple 폴더 설정) 테스트. 임시 폴더와 임시 .env 만 쓴다. 실행:
    python3 -m unittest discover -s tests -v
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import env_config  # noqa: E402


class AppleDirTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self._env_path, self._environ = env_config.ENV_PATH, dict(os.environ)
        env_config.ENV_PATH = self.root / ".env"
        os.environ.pop("APPLE_ACTIVITY_DIR", None)

    def tearDown(self):
        env_config.ENV_PATH = self._env_path
        os.environ.clear()
        os.environ.update(self._environ)
        self.tmp.cleanup()

    def make_export(self, *sub):
        folder = self.root.joinpath("export", *sub)
        folder.mkdir(parents=True)
        (folder / "Apple Music Play Activity.csv").write_text("x", encoding="utf-8")
        return folder

    def test_finds_folder_one_level_down_and_saves(self):
        inner = self.make_export("Apple Music Activity")
        status = env_config.save_config(None, None, str(self.root / "export"))
        self.assertEqual(status["apple_dir"], str(inner))
        self.assertTrue(status["apple_files"]["play_activity"])
        self.assertFalse(status["apple_files"]["library_xml"])
        self.assertEqual(os.environ["APPLE_ACTIVITY_DIR"], str(inner))     # 실행 중인 서버와 스크립트에도 바로 적용

    def test_missing_folder_or_no_apple_files_is_rejected_and_nothing_saved(self):
        (self.root / "empty").mkdir()
        for bad in (str(self.root / "nope"), str(self.root / "empty")):
            with self.assertRaises(ValueError):
                env_config.save_config("KEY", "me", bad)
        self.assertFalse(env_config.ENV_PATH.exists())                       # 검증에 실패하면 다른 값도 저장하지 않는다

    def test_none_keeps_and_empty_clears(self):
        folder = self.make_export()
        env_config.save_config("KEY", "me", str(folder))
        self.assertEqual(env_config.save_config(None, None, None)["apple_dir"], str(folder))   # 변경 없음
        cleared = env_config.save_config(None, None, "")
        self.assertEqual(cleared["apple_dir"], "")
        self.assertNotIn("APPLE_ACTIVITY_DIR", os.environ)
        self.assertTrue(cleared["has_api_key"])                                                # 다른 값은 그대로


if __name__ == "__main__":
    unittest.main()
