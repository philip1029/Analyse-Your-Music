import hashlib
import json
import threading
import time
from pathlib import Path

import requests

BASE_URL = "http://ws.audioscrobbler.com/2.0/"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "albums"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Last.fm이 "커버 없음"일 때 돌려주는 회색 기본 이미지의 해시 (이미지 필드가 빈 문자열인 경우가 대부분이지만 대비)
PLACEHOLDER_HASH = "2a96cbd8b46e442fc41c2b86b821562f"
# 커버를 못 찾은 결과도 캐시에 남기되, 나중에 Last.fm에 등록될 수 있으니 이 기간이 지나면 다시 시도한다
MISS_RETRY_SECONDS = 7 * 24 * 3600
# 큰 이미지부터 고른다 (extralarge/mega = 300x300)
SIZE_PREFERENCE = ("extralarge", "mega", "large", "medium", "small")
# 일시적 오류(요청 한도 초과 등)라서 "없음"으로 캐시하면 안 되는 Last.fm 오류 코드
TRANSIENT_ERROR_CODES = {8, 11, 16, 29}

_api_lock = threading.Lock()


def _cache_path(artist: str, album: str) -> Path:
    # 일본어·중국어 이름도 구별되도록 이름 자체가 아니라 해시로 파일명을 만든다
    key = f"{artist.strip().lower()}\x00{album.strip().lower()}"
    return CACHE_DIR / f"{hashlib.sha1(key.encode('utf-8')).hexdigest()}.json"


def _pick_image(images: list[dict]) -> str | None:
    by_size = {img.get("size", ""): img.get("#text", "") for img in images or []}
    for size in SIZE_PREFERENCE:
        url = by_size.get(size, "")
        if url and PLACEHOLDER_HASH not in url:
            return url
    return None


def get_album_art(artist: str, album: str, api_key: str) -> dict:
    """
    앨범 커버 주소를 반환한다: {"url": str | None, "cached": bool}.
    디스크 캐시(backend/cache/albums)를 먼저 보고, 없으면 album.getInfo 를 호출해 저장한다.
    네트워크 오류·요청 한도 초과처럼 일시적인 실패는 캐시하지 않는다.
    """
    artist, album = (artist or "").strip(), (album or "").strip()
    if not artist or not album:
        return {"url": None, "cached": False}

    path = _cache_path(artist, album)
    if path.exists():
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            if entry.get("url") or time.time() - entry.get("fetched_at", 0) < MISS_RETRY_SECONDS:
                return {"url": entry.get("url"), "cached": True}
        except (OSError, ValueError):
            pass  # 깨진 캐시 파일은 다시 받는다

    params = {
        "method": "album.getInfo",
        "artist": artist,
        "album": album,
        "autocorrect": 1,
        "api_key": api_key,
        "format": "json",
    }
    with _api_lock:  # 한꺼번에 몰려도 Last.fm 에는 순서대로, 간격을 두고 요청한다
        try:
            data = requests.get(BASE_URL, params=params, timeout=10).json()
        except Exception:
            return {"url": None, "cached": False}
        time.sleep(0.2)

    if "error" in data and data["error"] in TRANSIENT_ERROR_CODES:
        return {"url": None, "cached": False}

    url = _pick_image(data.get("album", {}).get("image", []))
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps({"artist": artist, "album": album, "url": url, "fetched_at": int(time.time())}, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)
    return {"url": url, "cached": False}
