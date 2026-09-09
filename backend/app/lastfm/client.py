import os
import re
import json
import time
from pathlib import Path
import requests

BASE_URL = "http://ws.audioscrobbler.com/2.0/"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "artists"
CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _slugify(artist_name: str) -> str:
    """아티스트명을 파일명으로 쓸 수 있게 변환한다."""
    slug = artist_name.lower().strip()
    slug = re.sub(r"[^a-z0-9가-힣]+", "_", slug)
    return slug.strip("_") or "unknown"

ALIAS_FILE = Path(__file__).resolve().parent.parent.parent.parent / "config" / "artist_aliases.txt"


def load_artist_aliases() -> dict[str, str]:
    """
    config/artist_aliases.txt를 읽어서 {원본이름: 교체이름} 딕셔너리로 반환.
    파일이 없거나 형식이 안 맞는 줄은 무시한다.
    """
    aliases: dict[str, str] = {}

    if not ALIAS_FILE.exists():
        return aliases

    with open(ALIAS_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "->" not in line:
                continue
            original, replacement = line.split("->", 1)
            aliases[original.strip()] = replacement.strip()

    return aliases


def resolve_artist_name(artist_name: str) -> str:
    """매핑 파일에 등록된 이름이면 교체된 이름을, 아니면 원본을 그대로 반환."""
    aliases = load_artist_aliases()
    return aliases.get(artist_name, artist_name)

def get_artist_top_tags(artist_name: str, api_key: str) -> list[dict]:
    """
    아티스트의 top tags를 가져온다.
    캐시에 있으면 캐시에서, 없으면 API 호출 후 캐시에 저장한다.
    반환 형식: [{"name": "shoegaze", "count": 100}, ...]
    """
    resolved_name = resolve_artist_name(artist_name)
    cache_path = CACHE_DIR / f"{_slugify(resolved_name)}.json"

    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            return json.load(f)

    params = {
        "method": "artist.gettoptags",
        "artist": resolved_name,
        "api_key": api_key,
        "format": "json",
    }

    try:
        response = requests.get(BASE_URL, params=params, timeout=10)
        data = response.json()
        tags = data.get("toptags", {}).get("tag", [])

        cleaned_tags = [
            {"name": t.get("name", ""), "count": int(t.get("count", 0))}
            for t in tags
            if t.get("name")
        ]
    except Exception:
        cleaned_tags = []

    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cleaned_tags, f, ensure_ascii=False, indent=2)

    time.sleep(0.2)
    return cleaned_tags

def invalidate_aliased_cache() -> list[str]:
    """
    alias 파일에 등록된 아티스트들의 캐시 파일을 전부 지운다.
    (원본 이름 기준 캐시, 교체된 이름 기준 캐시 둘 다 지워서 확실하게 재요청되도록 함)
    지워진 파일 이름 목록을 반환한다.
    """
    aliases = load_artist_aliases()
    deleted = []

    for original_name, replacement_name in aliases.items():
        for name in (original_name, replacement_name):
            cache_path = CACHE_DIR / f"{_slugify(name)}.json"
            if cache_path.exists():
                cache_path.unlink()
                deleted.append(cache_path.name)

    return deleted