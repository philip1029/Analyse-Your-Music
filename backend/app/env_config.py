import os
from pathlib import Path

from dotenv import dotenv_values, set_key

ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


def get_config_status() -> dict:
    """
    API 키 자체는 돌려주지 않고(화면에 평문으로 남기지 않기 위해),
    설정 여부와 유저네임(민감하지 않음)만 반환한다.
    """
    if not ENV_PATH.exists():
        return {"has_api_key": False, "username": ""}

    values = dotenv_values(ENV_PATH)
    return {
        "has_api_key": bool(values.get("LASTFM_API_KEY")),
        "username": values.get("USERNAME") or "",
    }


def save_config(api_key: str | None, username: str | None) -> dict:
    """
    빈 값은 "변경하지 않음"으로 취급한다 (API 키를 화면에 다시 보여주지 않으므로,
    유저네임만 바꾸고 싶을 때 키 입력칸을 비워두면 기존 키가 그대로 유지되어야 함).
    """
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

    return get_config_status()
