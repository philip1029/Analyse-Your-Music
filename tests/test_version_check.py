"""version_check (GitHub 최신 커밋과 비교한 업데이트 알림) 테스트. 임시 git 저장소만 쓴다. 실행:
    python3 -m unittest discover -s tests -v
"""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app import version_check  # noqa: E402


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout.strip()


class RemoteInHistoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        git(self.repo, "init", "-q")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "t")
        for name in ("a", "b"):
            (self.repo / name).write_text(name)
            git(self.repo, "add", name)
            git(self.repo, "commit", "-q", "-m", name)
        self.first = git(self.repo, "rev-list", "--max-parents=0", "HEAD")
        self._root = version_check.REPO_ROOT
        version_check.REPO_ROOT = self.repo

    def tearDown(self):
        version_check.REPO_ROOT = self._root
        self.tmp.cleanup()

    def test_remote_behind_me_is_not_an_update(self):
        # 원격 최신 = 내 첫 커밋, 나는 그 위에 푸시 안 한 커밋이 있음
        self.assertTrue(version_check._remote_in_local_history(self.first))

    def test_remote_equal_to_head(self):
        self.assertTrue(version_check._remote_in_local_history(git(self.repo, "rev-parse", "HEAD")))

    def test_unknown_remote_commit_is_an_update(self):
        self.assertFalse(version_check._remote_in_local_history("0123456789abcdef0123456789abcdef01234567"))

    def test_diverged_remote_is_an_update(self):
        git(self.repo, "checkout", "-q", "-b", "other", self.first)
        (self.repo / "c").write_text("c")
        git(self.repo, "add", "c")
        git(self.repo, "commit", "-q", "-m", "c")
        other = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "-")
        self.assertFalse(version_check._remote_in_local_history(other))


class SemverTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(version_check.parse_semver("1.2.3"), (1, 2, 3, None))
        self.assertEqual(version_check.parse_semver("v0.1.0-beta"), (0, 1, 0, "beta"))
        self.assertEqual(version_check.parse_semver("1.0.0-rc.1+build.5"), (1, 0, 0, "rc.1"))

    def test_parse_rejects_non_semver(self):
        for bad in (None, "", "1.2", "01.2.3", "1.2.3.4", "abc", "1.2.3-"):
            self.assertIsNone(version_check.parse_semver(bad), bad)

    def test_bump_kind(self):
        cases = [
            ("0.1.0", "1.0.0", "major"),
            ("0.1.0", "0.2.0", "minor"),
            ("0.1.0", "0.1.1", "patch"),
            ("0.1.0-beta", "0.1.0", "pre"),
            ("0.1.0-beta", "0.1.0-beta.2", "pre"),
            ("0.1.0-beta.2", "0.1.0-beta.11", "pre"),
            ("0.1.0-alpha", "0.1.0-beta", "pre"),
            ("0.1.0-beta", "0.2.0-beta", "minor"),
        ]
        for local, remote, kind in cases:
            self.assertEqual(version_check.bump_kind(local, remote), kind, (local, remote))

    def test_bump_kind_none_when_not_newer_or_unparseable(self):
        for local, remote in [("0.2.0", "0.1.0"), ("0.1.0", "0.1.0"), ("0.1.0", "0.1.0-beta"), ("0.1.0-beta", "0.1.0-alpha"), (None, "0.2.0"), ("0.1.0", "x")]:
            self.assertIsNone(version_check.bump_kind(local, remote), (local, remote))


class LocalVersionTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._root = version_check.REPO_ROOT
        version_check.REPO_ROOT = Path(self.tmp.name)

    def tearDown(self):
        version_check.REPO_ROOT = self._root
        self.tmp.cleanup()

    def test_reads_version_file(self):
        (Path(self.tmp.name) / "VERSION").write_text("0.1.0-beta\n")
        self.assertEqual(version_check.read_local_version(), "0.1.0-beta")

    def test_missing_or_invalid_file_is_none(self):
        self.assertIsNone(version_check.read_local_version())
        (Path(self.tmp.name) / "VERSION").write_text("not a version")
        self.assertIsNone(version_check.read_local_version())

    def test_repo_version_file_is_valid(self):
        real = (self._root / "VERSION").read_text().strip()
        self.assertIsNotNone(version_check.parse_semver(real))


if __name__ == "__main__":
    unittest.main()
