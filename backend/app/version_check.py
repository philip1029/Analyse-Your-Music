import re
import subprocess
import time
from pathlib import Path

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
CACHE_TTL_SECONDS = 3600

_cache: dict | None = None
_cache_at: float = 0.0

# https://semver.org 의 정식 정규식 (MAJOR.MINOR.PATCH[-프리릴리스][+빌드])
_SEMVER = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
    r"(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?"
    r"(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$"
)


def parse_semver(text: str | None) -> tuple[int, int, int, str | None] | None:
    """'1.2.3' → (1, 2, 3, None), '1.2.3-beta.1' → (1, 2, 3, 'beta.1'). 형식이 아니면 None. 빌드 메타데이터는 무시한다."""
    match = _SEMVER.match((text or "").strip().removeprefix("v"))
    if not match:
        return None
    major, minor, patch, pre, _build = match.groups()
    return int(major), int(minor), int(patch), pre


def bump_kind(local: str | None, remote: str | None) -> str | None:
    """내 버전에서 원격 버전으로 갈 때 어느 자리가 올랐는지: 'major' | 'minor' | 'patch' | 'pre'.
    파싱이 안 되거나 원격이 더 높지 않으면 None."""
    a, b = parse_semver(local), parse_semver(remote)
    if not a or not b:
        return None
    for index, kind in enumerate(("major", "minor", "patch")):
        if b[index] != a[index]:
            return kind if b[index] > a[index] else None
    # 숫자가 같으면 프리릴리스 비교: 정식(프리릴리스 없음) > 프리릴리스, 프리릴리스끼리는 식별자 순서대로
    if a[3] and (not b[3] or _pre_key(b[3]) > _pre_key(a[3])):
        return "pre"
    return None


def _pre_key(pre: str) -> list[tuple[int, int, str]]:
    """프리릴리스 식별자 비교 키: 숫자 식별자는 숫자로, 문자 식별자는 사전순으로, 숫자 < 문자 (semver 규칙 11)."""
    return [(0, int(part), "") if part.isdigit() else (1, 0, part) for part in pre.split(".")]


def read_local_version() -> str | None:
    """저장소 루트 VERSION 파일의 버전. 파일이 없거나 형식이 틀리면 None (업데이트 확인은 커밋 비교로 계속 동작)."""
    try:
        text = (REPO_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return text if parse_semver(text) else None


def _fetch_remote_version(owner: str, repo: str) -> str | None:
    try:
        response = requests.get(f"https://raw.githubusercontent.com/{owner}/{repo}/main/VERSION", timeout=5)
        response.raise_for_status()
    except Exception:
        return None
    text = response.text.strip()
    return text if parse_semver(text) else None


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


def _remote_in_local_history(remote_sha: str) -> bool:
    """GitHub 최신 커밋이 이미 내 로컬 기록에 들어 있는지 (내가 앞서 있으면 받을 업데이트가 아니다)."""
    try:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", remote_sha, "HEAD"],
            cwd=REPO_ROOT,
            capture_output=True,
            timeout=5,
        )
    except Exception:
        return False
    return result.returncode == 0       # 1: 조상이 아님, 128: 내 저장소에 없는 커밋 → 둘 다 받을 업데이트가 있다


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

    local_version = read_local_version()
    result = {"checked": False, "update_available": False, "local_version": local_version}

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

    update_available = remote_sha != local_sha and not _remote_in_local_history(remote_sha)
    remote_version = _fetch_remote_version(owner, repo) if update_available else local_version
    result = {
        "checked": True,
        # 같거나, 원격 최신 커밋이 이미 내 기록 안에 있으면(= 내가 푸시하지 않은 커밋만 더 있으면) 받을 업데이트가 아니다
        "update_available": update_available,
        "local_version": local_version,
        "remote_version": remote_version,
        "bump": bump_kind(local_version, remote_version) if update_available else None,
        "local_sha": local_sha[:7],
        "remote_sha": remote_sha[:7],
        "remote_message": remote_message,
    }
    _cache, _cache_at = result, now
    return result


def apply_update() -> dict:
    """
    git pull origin main을 실제로 실행한다. 충돌/네트워크 오류 등은 그대로
    git의 출력(output)에 담아 반환하고, 예외를 던지지 않는다.
    성공하면 check_for_update()의 캐시를 지워서 다음 조회 때 바로 최신 상태로 보이게 한다.
    uvicorn은 --reload로 떠있으므로, pull로 백엔드 파일이 바뀌면 서버가 알아서 재시작된다.
    """
    global _cache

    try:
        result = subprocess.run(
            ["git", "pull", "origin", "main"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as e:
        return {"success": False, "output": f"git pull 실행 실패: {e}"}

    output = (result.stdout + result.stderr).strip()
    success = result.returncode == 0

    if success:
        _cache = None

    return {"success": success, "output": output}
