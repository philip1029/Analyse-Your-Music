"""
좋아요(♥) 표시한 곡. data/favorites.json 에 [{"artist", "track", "added"}] 로 저장한다 (개인 데이터라 git 에 올라가지 않는다).

저장은 표기가 아니라 곡 이름(대소문자·띄어쓰기·기호 무시) + 아티스트로 알아본다. 그래서 병합으로 표기가 바뀌거나, 같은 곡이 크레딧 표기만 다르게
기록돼 있어도 같은 곡으로 센다 (Library 의 곡 항목과 같은 기준 = library.select_rows). 기록에서 곡을 못 찾으면 목록에는 남기되 found=False 로 돌려준다.
"""

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.analysis.duration_store import durations
from app.analysis.keys import name_key, resolve_all
from app.analysis.library import _top_album_per_key, select_rows

FILE_NAME = "favorites.json"


def load(path: Path) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [d for d in data if isinstance(d, dict) and isinstance(d.get("track"), str) and d["track"]]


def save(path: Path, items: list[dict]) -> None:
    """임시 파일에 쓴 뒤 바꿔치기해서, 쓰다가 끊겨도 기존 목록이 깨지지 않게 한다."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".favorites-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _ident(artist: str | None, track: str) -> tuple[str, str]:
    return name_key(track), name_key(artist) if artist else ""


def track_keys(df: pd.DataFrame) -> pd.Series:
    """행마다 곡 이름의 name_key. 곡을 여러 개 찾을 때 한 번만 계산해서 넘긴다."""
    names = df["track"].fillna("").astype(str)
    return names.map({n: name_key(n) for n in pd.unique(names)})


def _rows(df: pd.DataFrame, artist: str | None, track: str, nk: pd.Series | None = None) -> pd.DataFrame:
    """곡 하나의 행들 (select_rows 와 같은 기준). 이름이 같은 행만 먼저 추려서 계산이 가볍다."""
    sub = df[(track_keys(df) if nk is None else nk) == name_key(track)]
    return select_rows(sub, "track", artist, track) if len(sub) else sub


def canonical(df: pd.DataFrame, artist: str | None, track: str, nk: pd.Series | None = None) -> tuple[str | None, str]:
    """기록에서 이 곡의 대표 아티스트와 표시 이름. 기록에 없으면 받은 그대로."""
    rows = _rows(df, artist, track, nk)
    if rows.empty:
        return (artist or None), track
    _, reps, names = resolve_all(rows, "track")
    return (reps.iloc[0] or None), names.iloc[0]


def set_favorite(path: Path, df: pd.DataFrame, artist: str | None, track: str, favorite: bool) -> bool:
    """좋아요를 켜거나 끈다. 이미 그 상태면 아무것도 바꾸지 않는다. 바뀌었으면 True."""
    track = (track or "").strip()
    if not track:
        raise ValueError("곡 이름이 비어 있습니다.")
    nk = track_keys(df)
    rep, shown = canonical(df, artist, track, nk)
    ident = _ident(rep, shown)
    items = load(path)

    def same(it: dict) -> bool:
        # 저장된 표기가 지금의 대표 표기와 달라도(병합 등) 같은 곡이면 같은 항목으로 본다
        if _ident(it.get("artist"), it["track"]) == ident:
            return True
        r, s = canonical(df, it.get("artist"), it["track"], nk)
        return _ident(r, s) == ident

    kept = [it for it in items if not same(it)]
    exists = len(kept) != len(items)
    if favorite and not exists:
        kept.append({"artist": rep, "track": shown, "added": datetime.now().strftime("%Y-%m-%d")})
        save(path, kept)
        return True
    if not favorite and exists:
        save(path, kept)
        return True
    return False


def list_favorites(path: Path, df: pd.DataFrame) -> list[dict]:
    """
    좋아요한 곡 목록, 최근에 누른 순. 항목마다 현재 기록 기준의 대표 이름·아티스트와 재생 수·처음/마지막으로 들은 날(KST)을 붙인다.
    artists 는 이 곡의 기록에 쓰인 모든 아티스트 표기 (화면이 곡 목록의 하트를 칠할 때 쓴다).
    """
    out = []
    nk = track_keys(df)
    for it in load(path):
        rows = _rows(df, it.get("artist"), it["track"], nk)
        base = {"artist": it.get("artist") or None, "name": it["track"], "added": it.get("added") or "", "found": False,
                "artists": [it["artist"]] if it.get("artist") else [], "album": None, "duration": None,
                "scrobbles": 0, "first_played": None, "last_played": None}
        if rows.empty:
            out.append(base)
            continue
        _, reps, names = resolve_all(rows, "track")
        rep, shown = reps.iloc[0] or None, names.iloc[0]
        kst = pd.to_datetime(rows["utc_time"], utc=True, format="mixed").dt.tz_convert("Asia/Seoul")
        alb = _top_album_per_key(rows, pd.Series("k", index=rows.index), {"k"}).get("k")
        artists = sorted({a for a in rows["artist"].fillna("").astype(str) if a})
        out.append({**base, "artist": rep, "name": shown, "found": True, "artists": artists, "album": alb,
                    "duration": durations.get(rep or "", shown), "scrobbles": int(len(rows)),
                    "first_played": kst.min().strftime("%Y-%m-%d"), "last_played": kst.max().strftime("%Y-%m-%d")})
    out.sort(key=lambda d: (d["added"], d["name"]), reverse=True)
    return out


def find_track(df: pd.DataFrame, title: str, artist: str = "", nk: pd.Series | None = None) -> list[dict]:
    """
    "곡명 (+ 아티스트)"로 기록의 곡 후보를 찾는다 (이름은 대소문자·띄어쓰기·기호 무시, 완전 일치만).
    아티스트를 주면 그 이름과 맞는 후보만 남긴다. 반환: [{"artist", "name", "count"}] 많이 들은 순.
    """
    sub = df[(track_keys(df) if nk is None else nk) == name_key(title)]     # 아티스트와 상관없이 이 이름의 곡 전부
    if sub.empty:
        return []
    keys, reps, names = resolve_all(sub, "track")
    work = pd.DataFrame({"k": keys, "artist": reps, "name": names})
    work = work[work["k"] != ""]
    found = work.groupby(["artist", "name"]).size().reset_index(name="count").sort_values(["count", "name"], ascending=[False, True])
    if artist:
        ak = name_key(artist)
        found = found[found["artist"].map(lambda a: bool(a) and (name_key(a) == ak or ak in name_key(a) or name_key(a) in ak))]
    return [{"artist": r.artist or None, "name": r.name, "count": int(r.count)} for r in found.itertuples()]


def parse_line(line: str) -> tuple[str, str] | None:
    """'곡명 - 아티스트' 한 줄 -> (곡명, 아티스트). 구분(" - ")이 없으면 아티스트는 빈 값. 빈 줄은 None."""
    line = line.strip()
    if not line:
        return None
    if " - " in line:
        title, artist = line.rsplit(" - ", 1)
        return title.strip(), artist.strip()
    return line, ""
