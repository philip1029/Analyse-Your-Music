import os
from pathlib import Path

from dotenv import dotenv_values, set_key, unset_key

ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"

# Apple Music 개인정보 내보내기 폴더에서 앱이 읽는 파일 (없어도 앱은 Last.fm 데이터만으로 동작하고, 해당 기능만 건너뛴다)
APPLE_FILES = {
    "play_activity": ["Apple Music Play Activity.csv"],                                    # 가짜/중복 스크로블 판정
    "library_tracks": ["Apple Music Library Tracks.json.zip", "Apple Music Library Tracks.json"],   # 보관함 곡 목록: 정확한 곡 길이
    "daily_tracks": ["Apple Music - Play History Daily Tracks.csv"],                      # 빈 아티스트 채우기
    "library_xml": ["전체.xml"],                                                            # 음악 앱에서 내보낸 보관함: 곡 길이·아티스트 보강
}


def _apple_files_in(folder: Path) -> dict[str, bool]:
    return {key: any((folder / name).exists() for name in names) for key, names in APPLE_FILES.items()}


def resolve_apple_dir(raw: str) -> Path | None:
    """입력한 경로에서 Apple 내보내기 파일이 있는 폴더를 찾는다. 압축을 푼 맨 위 폴더를 줘도 한두 단계 아래까지 찾아 준다."""
    base = Path(raw.strip()).expanduser()
    if not base.is_dir():
        return None
    folders, level = [base], [base]
    for _ in range(2):                         # 맨 위 폴더 → 한 단계 아래 → 두 단계 아래 순으로 찾는다
        try:
            level = [c for f in level for c in sorted(p for p in f.iterdir() if p.is_dir())]
        except OSError:
            break
        folders += level
    for folder in folders:
        if any(_apple_files_in(folder).values()):
            return folder
    return None


def get_config_status() -> dict:
    """
    API 키 자체는 돌려주지 않고(화면에 평문으로 남기지 않기 위해),
    설정 여부와 유저네임(민감하지 않음)만 반환한다. Apple 폴더는 경로와 찾은 파일을 알려 준다.
    """
    values = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    apple_dir = values.get("APPLE_ACTIVITY_DIR") or ""
    return {
        "has_api_key": bool(values.get("LASTFM_API_KEY")),
        "username": values.get("USERNAME") or "",
        "apple_dir": apple_dir,
        "apple_files": _apple_files_in(Path(apple_dir)) if apple_dir and Path(apple_dir).is_dir() else {},
    }


def save_config(api_key: str | None, username: str | None, apple_dir: str | None = None) -> dict:
    """
    빈 값은 "변경하지 않음"으로 취급한다 (API 키를 화면에 다시 보여주지 않으므로,
    유저네임만 바꾸고 싶을 때 키 입력칸을 비워두면 기존 키가 그대로 유지되어야 함).
    apple_dir 만 예외: None 이면 변경 없음, 빈 문자열이면 설정을 지운다, 값이 있으면 폴더를 확인해서 저장한다
    (폴더가 없거나 Apple 파일이 하나도 없으면 ValueError, 아무것도 저장하지 않는다).
    """
    resolved: Path | None = None
    if apple_dir is not None and apple_dir.strip():
        resolved = resolve_apple_dir(apple_dir)
        if resolved is None:
            names = ", ".join(n for v in APPLE_FILES.values() for n in v)
            raise ValueError(f"Apple Music 폴더를 찾지 못했어요. 폴더가 있는지, 안에 다음 파일 중 하나가 있는지 확인하세요: {names}")

    if not ENV_PATH.exists():
        ENV_PATH.touch()

    if api_key and api_key.strip():
        value = api_key.strip()
        set_key(str(ENV_PATH), "LASTFM_API_KEY", value)
        os.environ["LASTFM_API_KEY"] = value

    if username and username.strip():
        value = username.strip()
        set_key(str(ENV_PATH), "USERNAME", value)
        os.environ["USERNAME"] = value

    if apple_dir is not None:
        if resolved is not None:
            set_key(str(ENV_PATH), "APPLE_ACTIVITY_DIR", str(resolved))
            os.environ["APPLE_ACTIVITY_DIR"] = str(resolved)
        else:
            unset_key(str(ENV_PATH), "APPLE_ACTIVITY_DIR")
            os.environ.pop("APPLE_ACTIVITY_DIR", None)

    return get_config_status()
