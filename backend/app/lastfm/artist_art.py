import hashlib
import json
import re
import threading
import time
import unicodedata
from pathlib import Path

import requests

# Last.fm 은 2019년부터 아티스트 사진을 제공하지 않고 모든 아티스트에 같은 회색 기본 이미지만 돌려준다.
# 그래서 아티스트 사진만 Deezer 공개 검색 API(키 불필요)에서 가져온다.
SEARCH_URL = "https://api.deezer.com/search/artist"
CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "artist_images"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Deezer 에 다른 이름(영문 등)으로 등록된 아티스트: "내 데이터의 이름 -> Deezer 검색 이름"
NAMES_FILE = Path(__file__).resolve().parent.parent.parent.parent / "config" / "artist_photo_names.txt"

# 못 찾은 결과도 캐시에 남기되, 이 기간이 지나면 다시 시도한다
MISS_RETRY_SECONDS = 7 * 24 * 3600
# Deezer 가 사진이 없는 아티스트에 돌려주는 빈 이미지는 주소에 해시 대신 빈 폴더가 들어간다 (".../artist//250x250...")
_api_lock = threading.Lock()


def _key(name: str) -> str:
    """대소문자·띄어쓰기·구두점 차이를 무시하는 비교 키."""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", name).lower())


def load_photo_names() -> dict[str, str]:
    names: dict[str, str] = {}
    if NAMES_FILE.exists():
        for line in NAMES_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "->" in line:
                a, b = line.split("->", 1)
                if a.strip() and b.strip():
                    names[a.strip()] = b.strip()
    return names


def _cache_path(artist: str) -> Path:
    return CACHE_DIR / f"{hashlib.sha1(artist.strip().lower().encode('utf-8')).hexdigest()}.json"


def _pick(artist: str, results: list[dict]) -> str | None:
    """검색 결과 중 이름이 같은 아티스트의 사진 주소. 이름이 다르면 엉뚱한 사람일 수 있어 쓰지 않는다."""
    want = _key(artist)
    for r in results:
        if _key(r.get("name", "")) == want:
            url = r.get("picture_big") or r.get("picture_medium") or ""
            return url if url and "/artist//" not in url else None
    return None


def get_artist_art(artist: str) -> dict:
    """아티스트 사진 주소를 반환한다: {"url": str | None, "cached": bool}. 일시적 실패는 캐시하지 않는다."""
    artist = (artist or "").strip()
    if not artist:
        return {"url": None, "cached": False}

    path = _cache_path(artist)
    search_name = load_photo_names().get(artist, artist)
    if path.exists():
        try:
            entry = json.loads(path.read_text(encoding="utf-8"))
            if entry.get("url") or time.time() - entry.get("fetched_at", 0) < MISS_RETRY_SECONDS:
                return {"url": entry.get("url"), "cached": True}
        except (OSError, ValueError):
            pass

    with _api_lock:
        try:
            resp = requests.get(SEARCH_URL, params={"q": search_name, "limit": 5}, timeout=10)
            data = resp.json()
        except Exception:
            return {"url": None, "cached": False}
        time.sleep(0.2)

    if "error" in data or "data" not in data:  # 요청 한도 초과 등
        return {"url": None, "cached": False}

    url = _pick(search_name, data["data"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"artist": artist, "url": url, "fetched_at": int(time.time())}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return {"url": url, "cached": False}
