"""앨범 커버 누락 점검: 많이 들은 앨범 중 커버를 못 찾은 것을 모아서 사용자가 직접 채울 수 있게 한다."""

import pandas as pd

from app.analysis.library import ranked_page
from app.lastfm import album_art, cover_overrides


def _classify(df: pd.DataFrame, top: int):
    items = ranked_page(df, "album", 0, top, "plays")["items"]
    missing, unchecked, found, manual = [], [], 0, 0
    for it in items:
        artist, name = it["artist"] or "", it["name"]
        if cover_overrides.get_url("album", artist, name):
            manual += 1
        elif not artist:                                    # 아티스트가 없으면 Last.fm 에서 앨범을 찾을 수 없다
            missing.append({"name": name, "artist": None, "count": it["count"], "reason": "아티스트 정보가 없음"})
        else:
            state = album_art.cached_state(artist, name)
            if state == "hit":
                found += 1
            elif state == "miss":
                missing.append({"name": name, "artist": artist, "count": it["count"], "reason": "자동으로 못 찾음"})
            else:
                unchecked.append(it)
    return items, missing, unchecked, found, manual


def audit_albums(df: pd.DataFrame, top: int = 300) -> dict:
    items, missing, unchecked, found, manual = _classify(df, top)
    return {"top": len(items), "found": found, "manual": manual, "unchecked": len(unchecked), "missing": missing}


def check_unchecked(df: pd.DataFrame, api_key: str, limit: int = 30, top: int = 300) -> dict:
    """아직 한 번도 조회하지 않은 앨범을 재생 많은 순으로 limit 개까지 Last.fm 에서 조회한다 (캐시에 남는다)."""
    _, _, unchecked, _, _ = _classify(df, top)
    checked = found = 0
    for it in unchecked[:limit]:
        res = album_art.get_album_art(it["artist"], it["name"], api_key)
        checked += 1
        found += 1 if res.get("url") else 0
    return {"checked": checked, "found": found, "remaining": max(0, len(unchecked) - checked)}
