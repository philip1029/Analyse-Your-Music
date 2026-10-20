import pandas as pd

from app.analysis.keys import resolve_keys


def _top_album_per_key(df: pd.DataFrame, keys: pd.Series, wanted: set[str]) -> dict[str, str]:
    """곡(키)별로 가장 많이 기록된 앨범 (표지용). 필요한 키만 계산한다."""
    mask = keys.isin(wanted) & df["album"].notna() & (df["album"] != "")
    if not mask.any():
        return {}
    g = df[mask].assign(_key=keys[mask]).groupby(["_key", "album"]).size().reset_index(name="n")
    g = g.sort_values(["n", "album"], ascending=[False, True]).drop_duplicates("_key")
    return dict(zip(g["_key"], g["album"]))


def key_of(artist: str | None, name: str) -> str:
    return f"{artist} - {name}" if artist else name


def ranked_page(df: pd.DataFrame, category: str, offset: int = 0, limit: int = 50) -> dict:
    """Last.fm 라이브러리 같은 순위 목록. 반환: 전체 항목 수(고유), 전체 재생 수, 해당 구간 항목."""
    total_plays = int(len(df))
    if category == "artist":
        counts = df[df["artist"] != ""]["artist"].value_counts()
        page = counts.iloc[offset: offset + limit]
        items = [{"name": n, "artist": None, "album": None, "count": int(c)} for n, c in page.items()]
        return {"category": category, "total": int(len(counts)), "total_plays": total_plays, "offset": offset, "items": items}

    keys, reps = resolve_keys(df, category)
    valid = keys != ""
    counts = keys[valid].value_counts()
    page = counts.iloc[offset: offset + limit]
    first = df[valid].assign(_key=keys[valid], _rep=reps[valid]).drop_duplicates("_key").set_index("_key")
    album_of = _top_album_per_key(df, keys, set(page.index)) if category == "track" else {}
    items = []
    for key, c in page.items():
        row = first.loc[key]
        items.append({"name": row[category], "artist": row["_rep"] or None, "album": album_of.get(key), "count": int(c)})
    return {"category": category, "total": int(len(counts)), "total_plays": total_plays, "offset": offset, "items": items}


def artist_detail(df: pd.DataFrame, name: str) -> dict | None:
    rows = df[df["artist"] == name]
    if rows.empty:
        return None
    alb = rows[rows["album"] != ""]["album"].value_counts()
    trk = rows[rows["track"] != ""].groupby("track").size().sort_values(ascending=False, kind="stable")
    # 곡별 대표 앨범 (표지용)
    ta = rows[(rows["track"] != "") & (rows["album"] != "")].groupby(["track", "album"]).size().reset_index(name="n")
    ta = ta.sort_values(["n", "album"], ascending=[False, True]).drop_duplicates("track")
    album_of = dict(zip(ta["track"], ta["album"]))
    return {
        "name": name,
        "scrobbles": int(len(rows)),
        "albums_count": int(len(alb)),
        "tracks_count": int(len(trk)),
        "albums": [{"name": n, "artist": name, "count": int(c)} for n, c in alb.items()],
        "tracks": [{"name": n, "artist": name, "album": album_of.get(n), "count": int(c)} for n, c in trk.items()],
    }


def album_detail(df: pd.DataFrame, artist: str | None, name: str) -> dict | None:
    keys, _ = resolve_keys(df, "album")
    rows = df[keys == key_of(artist, name)]
    if rows.empty:
        return None
    trk = rows[rows["track"] != ""].groupby("track").size().sort_values(ascending=False, kind="stable")
    return {
        "name": name,
        "artist": artist,
        "scrobbles": int(len(rows)),
        "tracks_count": int(len(trk)),
        "tracks": [{"name": n, "artist": artist, "album": name, "count": int(c)} for n, c in trk.items()],
    }


def track_detail(df: pd.DataFrame, artist: str | None, name: str, offset: int = 0, limit: int = 50) -> dict | None:
    keys, _ = resolve_keys(df, "track")
    rows = df[keys == key_of(artist, name)]
    if rows.empty:
        return None
    kst = pd.to_datetime(rows["utc_time"], utc=True, format="mixed").dt.tz_convert("Asia/Seoul")
    rows = rows.assign(_kst=kst).sort_values("_kst", ascending=False, kind="stable")
    page = rows.iloc[offset: offset + limit]
    album_of = _top_album_per_key(rows, pd.Series(key_of(artist, name), index=rows.index), {key_of(artist, name)})
    return {
        "name": name,
        "artist": artist,
        "album": album_of.get(key_of(artist, name)),
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
