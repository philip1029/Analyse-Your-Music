import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _run(cmd: list[str], cwd: Path) -> dict:
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=300,
        )
        output = (result.stdout + result.stderr).strip()
        return {"success": result.returncode == 0, "output": output[-4000:]}
    except Exception as e:
        return {"success": False, "output": f"실행 실패: {e}"}


def install_deps() -> dict:
    """start.command가 켤 때마다 하는 것과 동일한 설치를 웹 화면에서 수동으로 다시 돌린다."""
    pip_result = _run(
        ["pip3", "install", "-r", str(REPO_ROOT / "backend" / "requirements.txt")],
        cwd=REPO_ROOT,
    )
    npm_result = _run(["npm", "install"], cwd=REPO_ROOT / "frontend")
    return {"pip": pip_result, "npm": npm_result}
