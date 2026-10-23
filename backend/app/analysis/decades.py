"""Music by decade: 들은 앨범의 발매 연대별 스크로블·앨범·아티스트 수. 연도는 album_years 모듈(MusicBrainz 우선 · Apple 보조 · 수동 보정)이 채운다."""

import pandas as pd

from app.analysis.keys import resolve_all
from app.lastfm.durations import norm

RELIABLE_COVERAGE = 0.7     # 스크로블 기준으로 이 비율 이상 연도를 알아야 "믿을 만한" 분포로 본다
TOP_PER_DECADE = 3
UNKNOWN_TOP = 8


def build_decades(df: pd.DataFrame, lookup) -> dict:
    """
    lookup.get(artist, album) -> {"year", "src", ...} 또는 None(조회 전). 앨범 키는 앱이 앨범을 세는 방식(resolve_all) 그대로다.
    연도를 모르는 앨범은 분포에서 빼고, 그 비중(coverage)을 함께 돌려줘서 화면이 믿을 만한 정도를 알려 줄 수 있게 한다.
    """
    total_plays = int(len(df))
    if total_plays == 0:
        return {"decades": [], "coverage": _coverage(0, 0, 0, 0), "reliable": False, "oldest": None, "newest": None, "sources": {}, "unknown_top": []}

    keys, reps, names = resolve_all(df, "album")
    valid = keys != ""
    work = pd.DataFrame({"key": keys[valid], "artist": reps[valid], "album": names[valid]})
    albums = work.groupby("key").agg(artist=("artist", "first"), album=("album", "first"), plays=("key", "size")).reset_index(drop=True)

    entries = [lookup.get(a, b) for a, b in zip(albums["artist"], albums["album"])]
    albums["year"] = [e["year"] if e else None for e in entries]
    albums["src"] = [e.get("src") if e else None for e in entries]
    albums["ambiguous"] = [bool(e.get("ambiguous")) if e else False for e in entries]
    albums["checked"] = [e is not None for e in entries]

    known = albums[albums["year"].notna()].copy()
    known["year"] = known["year"].astype(int)
    known["decade"] = known["year"] // 10 * 10
    unknown = albums[albums["year"].isna()]

    decades = []
    if len(known):
        for decade in range(int(known["decade"].min()), int(known["decade"].max()) + 1, 10):
            g = known[known["decade"] == decade].sort_values(["plays", "album"], ascending=[False, True])
            decades.append({
                "decade": decade,
                "label": f"{decade}s",
                "plays": int(g["plays"].sum()),
                "albums": int(len(g)),
                "artists": int(g["artist"].nunique()),
                "top": [
                    {"artist": r.artist, "album": r.album, "year": int(r.year), "plays": int(r.plays)}
                    for r in g.head(TOP_PER_DECADE).itertuples()
                ],
            })

    def pick(frame, ascending):
        if not len(frame):
            return None
        r = frame.sort_values(["year", "plays"], ascending=[ascending, False]).iloc[0]
        return {"artist": r["artist"], "album": r["album"], "year": int(r["year"])}

    known_plays = int(known["plays"].sum()) if len(known) else 0
    coverage = _coverage(known_plays, total_plays, len(known), len(albums))
    coverage["albums_unchecked"] = int((~albums["checked"]).sum())
    coverage["albums_not_found"] = int((albums["checked"] & albums["year"].isna()).sum())

    return {
        "decades": decades,
        "coverage": coverage,
        "reliable": coverage["pct"] >= RELIABLE_COVERAGE,
        "oldest": pick(known, True),
        "newest": pick(known, False),
        "sources": {k: int(v) for k, v in known["src"].fillna("?").value_counts().items()},
        "ambiguous_albums": int(known["ambiguous"].sum()) if len(known) else 0,
        "unknown_top": [
            {"artist": r.artist, "album": r.album, "plays": int(r.plays)}
            for r in unknown.sort_values(["plays", "album"], ascending=[False, True]).head(UNKNOWN_TOP).itertuples()
        ],
    }


def list_albums(pairs, lookup, q: str = "", only_unknown: bool = False, limit: int = 50, offset: int = 0) -> dict:
    """연도 편집 화면의 앨범 목록. pairs 는 album_years.album_pairs(df) 의 (아티스트, 앨범, 재생 수)이고 재생 많은 순 그대로다.
    q 는 아티스트·앨범 이름에 들어 있는지(대소문자·띄어쓰기·기호 무시), only_unknown 이면 연도를 모르는 앨범만."""
    needle = norm(q)
    items = []
    for artist, album, plays in pairs:
        if needle and needle not in norm(artist) + norm(album):
            continue
        entry = lookup.get(artist, album)
        year = entry.get("year") if entry else None
        if only_unknown and year:
            continue
        items.append({
            "artist": artist,
            "album": album,
            "plays": plays,
            "year": year,
            "src": entry.get("src") if entry else None,
            "manual": bool(entry) and entry.get("src") == "manual",
            "ambiguous": bool(entry and entry.get("ambiguous")),
            "checked": entry is not None,
        })
    return {"total": len(items), "items": items[max(0, offset): max(0, offset) + max(1, limit)]}


def _coverage(known_plays: int, total_plays: int, known_albums: int, total_albums: int) -> dict:
    return {
        "known_plays": known_plays,
        "total_plays": total_plays,
        "pct": round(known_plays / total_plays, 4) if total_plays else 0.0,
        "known_albums": known_albums,
        "total_albums": total_albums,
    }
