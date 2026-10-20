from pathlib import Path

import pandas as pd

from app.analysis.keys import name_key, resolve_all
from app.lastfm.durations import CACHE_NAME, DurationLookup

# data/track_durations.json (scripts/fill_durations.py 가 채움). 없으면 길이는 None.
durations = DurationLookup(Path(__file__).resolve().parents[3] / "data" / CACHE_NAME)


def _top_album_per_key(df: pd.DataFrame, keys: pd.Series, wanted: set[str]) -> dict[str, str]:
    """곡(키)별로 가장 많이 기록된 앨범 (표지용). 필요한 키만 계산한다."""
    mask = keys.isin(wanted) & df["album"].notna() & (df["album"] != "")
    if not mask.any():
        return {}
    g = df[mask].assign(_key=keys[mask]).groupby(["_key", "album"]).size().reset_index(name="n")
    g = g.sort_values(["n", "album"], ascending=[False, True]).drop_duplicates("_key")
    return dict(zip(g["_key"], g["album"]))


def ranked_page(df: pd.DataFrame, category: str, offset: int = 0, limit: int = 50) -> dict:
    """Last.fm 라이브러리 같은 순위 목록. 반환: 전체 항목 수(고유), 전체 재생 수, 해당 구간 항목."""
    total_plays = int(len(df))
    if category == "artist":
        counts = df[df["artist"] != ""]["artist"].value_counts()
        page = counts.iloc[offset: offset + limit]
        items = [{"name": n, "artist": None, "album": None, "count": int(c)} for n, c in page.items()]
        return {"category": category, "total": int(len(counts)), "total_plays": total_plays, "offset": offset, "items": items}

    keys, reps, names = resolve_all(df, category)
    valid = keys != ""
    counts = keys[valid].value_counts()
    page = counts.iloc[offset: offset + limit]
    first = df[valid].assign(_key=keys[valid], _rep=reps[valid], _name=names[valid]).drop_duplicates("_key").set_index("_key")
    album_of = _top_album_per_key(df, keys, set(page.index)) if category == "track" else {}
    items = []
    for key, c in page.items():
        row = first.loc[key]
        item = {"name": row["_name"], "artist": row["_rep"] or None, "album": album_of.get(key), "count": int(c)}
        if category == "track":
            item["duration"] = durations.get(item["artist"] or "", item["name"])
        items.append(item)
    return {"category": category, "total": int(len(counts)), "total_plays": total_plays, "offset": offset, "items": items}


def artist_detail(df: pd.DataFrame, name: str) -> dict | None:
    rows = df[df["artist"] == name]
    if rows.empty:
        return None
    # 대소문자·띄어쓰기만 다른 제목은 한 항목으로 센다 (표시 이름은 가장 많이 쓰인 표기)
    _, _, alb_names = resolve_all(rows, "album")
    _, _, trk_names = resolve_all(rows, "track")
    alb = alb_names[alb_names != ""].value_counts()
    trk = trk_names[trk_names != ""].value_counts()
    # 곡별 대표 앨범 (표지용)
    both = (trk_names != "") & (alb_names != "")
    ta = pd.DataFrame({"track": trk_names[both], "album": alb_names[both]}).groupby(["track", "album"]).size().reset_index(name="n")
    ta = ta.sort_values(["n", "album"], ascending=[False, True]).drop_duplicates("track")
    album_of = dict(zip(ta["track"], ta["album"]))
    return {
        "name": name,
        "scrobbles": int(len(rows)),
        "albums_count": int(len(alb)),
        "tracks_count": int(len(trk)),
        "albums": [{"name": n, "artist": name, "count": int(c)} for n, c in alb.items()],
        "tracks": [{"name": n, "artist": name, "album": album_of.get(n), "count": int(c), "duration": durations.get(name, n)} for n, c in trk.items()],
    }


def select_rows(df: pd.DataFrame, column: str, artist: str | None, name: str) -> pd.DataFrame:
    """
    곡/앨범 하나의 행들. 이름은 대소문자·띄어쓰기를 무시하고, 아티스트는 그 아티스트가 속한 크레딧 묶음 전체를 고른다
    (목록에 나온 아티스트 표기가 묶음의 어느 표기든 같은 항목을 찾도록).
    """
    want = name_key(name)
    sub = df[df[column].map(name_key) == want] if len(df) else df
    if sub.empty:
        return sub
    keys, reps, _ = resolve_all(sub, column)
    if artist:
        mine = sub["artist"] == artist
        if not mine.any():
            return sub.iloc[0:0]
        return sub[keys == keys[mine].iloc[0]]
    return sub[reps == ""]


def album_detail(df: pd.DataFrame, artist: str | None, name: str) -> dict | None:
    rows = select_rows(df, "album", artist, name)
    if rows.empty:
        return None
    _, _, album_names = resolve_all(rows, "album")
    # 곡은 대소문자 차이를 합쳐 세고, 곡 페이지가 열리도록 그 곡에서 가장 많이 쓰인 아티스트 표기를 함께 준다
    t_keys, _, t_names = resolve_all(rows, "track")
    ok = t_keys != ""
    work = rows[ok].assign(_tk=t_names[ok].map(name_key), _tn=t_names[ok])
    counts = work.groupby("_tk").size().sort_values(ascending=False, kind="stable")
    shown = work.drop_duplicates("_tk").set_index("_tk")["_tn"]
    dom_artist = work.groupby(["_tk", "artist"]).size().reset_index(name="n").sort_values(["n", "artist"], ascending=[False, True]).drop_duplicates("_tk").set_index("_tk")["artist"]
    tracks = []
    for tk, c in counts.items():
        tn, ta = shown[tk], dom_artist[tk] or None
        tracks.append({"name": tn, "artist": ta, "album": album_names.iloc[0], "count": int(c), "duration": durations.get(ta or "", tn)})
    return {
        "name": album_names.iloc[0],
        "artist": artist,
        "scrobbles": int(len(rows)),
        "tracks_count": len(tracks),
        "tracks": tracks,
    }


def track_detail(df: pd.DataFrame, artist: str | None, name: str, offset: int = 0, limit: int = 50, album: str | None = None) -> dict | None:
    """
    곡 하나의 청취 기록. 같은 곡이 여러 앨범(원곡·어레인지 앨범 등)에 들어 있으면 기본은 모두 모아 보여 주고
    (Last.fm 방식), album 을 주면 그 앨범에서 들은 기록만 보여 준다. albums 에 앨범별 재생 수가 들어 있다.
    """
    rows = select_rows(df, "track", artist, name)
    if rows.empty:
        return None
    _, reps, names = resolve_all(rows, "track")
    shown, rep = names.iloc[0], reps.iloc[0] or None
    _, _, alb_names = resolve_all(rows, "album")
    breakdown = alb_names[alb_names != ""].value_counts()
    scoped = None
    if album:
        rows = rows[alb_names.map(name_key) == name_key(album)]
        if rows.empty:
            return None
        scoped = alb_names[rows.index].iloc[0]
    kst = pd.to_datetime(rows["utc_time"], utc=True, format="mixed").dt.tz_convert("Asia/Seoul")
    rows = rows.assign(_kst=kst).sort_values("_kst", ascending=False, kind="stable")
    page = rows.iloc[offset: offset + limit]
    album_of = scoped or _top_album_per_key(rows, pd.Series("k", index=rows.index), {"k"}).get("k")
    return {
        "name": shown,
        "artist": rep,
        "album": album_of,
        "scope_album": scoped,
        "albums": [{"name": n, "count": int(c)} for n, c in breakdown.items()],
        "duration": durations.get(rep or "", shown),
        "scrobbles": int(len(rows)),
        "first_played": rows["_kst"].min().strftime("%Y-%m-%d"),
        "last_played": rows["_kst"].max().strftime("%Y-%m-%d"),
        "offset": offset,
        "plays": [
            {"time": r["_kst"].strftime("%Y-%m-%d %H:%M"), "album": r["album"] or None, "artist": r["artist"] or None,
             "source": r.get("source") if isinstance(r.get("source"), str) else None}
            for _, r in page.iterrows()
        ],
    }
