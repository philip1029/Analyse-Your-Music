import re
import subprocess
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_TTL_SECONDS = 3600

_cache: dict | None = None
_cache_at: float = 0.0


def _run_git(args: list[str]) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except Exception:
        return None


def _parse_owner_repo(remote_url: str) -> tuple[str, str] | None:
    # https://github.com/owner/repo(.git) 또는 git@github.com:owner/repo(.git) 둘 다 지원
    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+?)(\.git)?$", remote_url)
    if not match:
        return None
    return match.group(1), match.group(2)


def check_for_update() -> dict:
    """
    로컬 HEAD 커밋과 GitHub origin/main의 최신 커밋을 비교한다.
    실패(오프라인, git 정보 없음 등)해도 예외를 던지지 않고 checked=False로 반환한다.
    결과는 CACHE_TTL_SECONDS 동안 재사용해서 GitHub API를 과하게 호출하지 않는다.
    """
    global _cache, _cache_at

    now = time.time()
    if _cache is not None and (now - _cache_at) < CACHE_TTL_SECONDS:
        return _cache

    result = {"checked": False, "update_available": False}

    local_sha = _run_git(["rev-parse", "HEAD"])
    remote_url = _run_git(["remote", "get-url", "origin"])
    if not local_sha or not remote_url:
        _cache, _cache_at = result, now
        return result

    owner_repo = _parse_owner_repo(remote_url)
    if not owner_repo:
        _cache, _cache_at = result, now
        return result
    owner, repo = owner_repo

    try:
        response = requests.get(
            f"https://api.github.com/repos/{owner}/{repo}/commits/main",
            timeout=5,
        )
        response.raise_for_status()
        data = response.json()
        remote_sha = data.get("sha")
        remote_message = data.get("commit", {}).get("message", "").split("\n")[0]
    except Exception:
        _cache, _cache_at = result, now
        return result

    if not remote_sha:
        _cache, _cache_at = result, now
        return result

    result = {
        "checked": True,
        "update_available": remote_sha != local_sha,
        "local_sha": local_sha[:7],
        "remote_sha": remote_sha[:7],
        "remote_message": remote_message,
    }
    _cache, _cache_at = result, now
    return result
