import pandas as pd

from app.analysis.keys import name_key, resolve_all
from app.analysis.library import _top_album_per_key


def _rank(match_key: str, qk: str) -> int | None:
    """검색어와의 일치 정도: 0 = 완전 일치, 1 = 앞부분 일치, 2 = 포함, None = 불일치."""
    if qk == match_key:
        return 0
    if match_key.startswith(qk):
        return 1
    return 2 if qk in match_key else None


def search_library(df: pd.DataFrame, query: str, limit: int = 6) -> dict:
    """
    아티스트·앨범·곡을 이름으로 찾는다. 대소문자·띄어쓰기·기호는 무시하고(name_key), 곡/앨범은
    "아티스트 이름"을 이어 붙인 글자의 앞부분에서도 찾는다 (예: "pink floyd wish"). 완전 일치 > 앞부분 일치 > 포함 순,
    같으면 많이 들은 순. 각 종류 limit 개까지. 결과 항목은 Library 목록 항목과 같은 모양(name/artist/album/count).
    """
    empty = {"query": query, "artists": [], "albums": [], "tracks": []}
    qk = name_key(query.strip()) if query and query.strip() else ""
    if not qk:
        return empty

    # 아티스트
    counts = df.loc[df["artist"].fillna("") != "", "artist"].value_counts()
    hits = []
    for name, plays in counts.items():
        r = _rank(name_key(name), qk)
        if r is not None:
            hits.append((r, -int(plays), name))
    hits.sort()
    artists = [{"name": n, "artist": None, "album": None, "count": -neg} for _, neg, n in hits[:limit]]

    def by_column(column: str) -> list[dict]:
        # 전체를 묶는 계산(resolve_all)은 느리니, 검색어와 맞을 수 있는 이름의 행만 추려서 한다.
        # 이름 하나의 행은 통째로 가져오므로 묶음 결과는 전체로 계산한 것과 같다.
        name = df[column].fillna("").astype(str)
        art = df["artist"].fillna("").astype(str)
        pairs = pd.DataFrame({"n": name, "a": art})[name != ""].drop_duplicates()
        pair_keys = [(n, name_key(n), name_key(f"{a} {n}") if a else "") for n, a in zip(pairs["n"], pairs["a"])]
        wanted = {n for n, k1, k2 in pair_keys if qk in k1 or (k2 and k2.startswith(qk))}
        if not wanted:
            return []
        sub = df[name.isin(wanted)]
        keys, reps, names = resolve_all(sub, column)
        return _collect(sub, keys, reps, names, column)

    def _collect(df: pd.DataFrame, keys, reps, names, column: str) -> list[dict]:
        valid = keys != ""
        if not valid.any():
            return []
        sizes = keys[valid].value_counts()
        first = df[valid].assign(_key=keys[valid], _rep=reps[valid], _name=names[valid]).drop_duplicates("_key").set_index("_key")
        found = []
        for key, row in first.iterrows():
            name, rep = row["_name"], row["_rep"] or ""
            ranks = [_rank(name_key(name), qk)]
            if rep and name_key(f"{rep} {name}").startswith(qk):
                ranks.append(1)   # "아티스트 곡명" 순서로 친 검색어 (경계를 가로지르는 우연한 일치는 제외)
            ranks = [r for r in ranks if r is not None]
            if ranks:
                found.append((min(ranks), -int(sizes[key]), key, name, rep))
        found.sort()
        top = found[:limit]
        album_of = _top_album_per_key(df, keys, {k for _, _, k, _, _ in top}) if column == "track" else {}
        return [{"name": n, "artist": rep or None, "album": album_of.get(k), "count": -neg} for _, neg, k, n, rep in top]

    return {"query": query, "artists": artists, "albums": by_column("album"), "tracks": by_column("track")}
