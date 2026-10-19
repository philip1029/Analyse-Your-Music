import re
import unicodedata

import pandas as pd

# 공동 크레딧을 구성 요소로 나누는 구분자: "A & B", "A, B", "A / B", "A feat. B", "A with B", "A and B"
_CREDIT_SPLIT = re.compile(r"\s*,\s*|\s*&\s*|\s+/\s+|\s+(?:feat\.?|featuring|ft\.?|with|and)\s+", re.IGNORECASE)


def _credit_parts(artist: str) -> set[str]:
    parts = (re.sub(r"\s+", " ", unicodedata.normalize("NFKC", p).lower()).strip() for p in _CREDIT_SPLIT.split(artist))
    return {p for p in parts if p}


def _cluster_artists(counts: dict[str, int]) -> dict[str, str]:
    """
    한 곡명/앨범명 아래 나온 아티스트 표기들을 "같은 크레딧"끼리 묶는다.
    구성 요소(& , / feat. 로 나눈 이름)를 하나라도 공유하면 같은 묶음이다.
    (VISUAL ARTS / Key, LIA & VISUAL ARTS / Key → 같은 묶음, Jim O'Rourke 와 키노코 테이코쿠 → 다른 묶음)
    반환: {표기: 묶음 대표 표기 (묶음에서 가장 많이 쓰인 표기)}
    """
    names = sorted(counts)
    parent = {n: n for n in names}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    owner: dict[str, str] = {}
    for n in names:
        for part in _credit_parts(n):
            if part in owner:
                parent[find(n)] = find(owner[part])
            else:
                owner[part] = n

    groups: dict[str, list[str]] = {}
    for n in names:
        groups.setdefault(find(n), []).append(n)
    rep = {}
    for members in groups.values():
        top = sorted(members, key=lambda n: (-counts[n], n))[0]
        for n in members:
            rep[n] = top
    return rep


def resolve_keys(df: pd.DataFrame, column: str) -> tuple[pd.Series, pd.Series]:
    """
    집계용 (키, 대표 아티스트). 곡명·앨범명만 같은 다른 아티스트의 항목(Untitled, Eureka, Romance 등)은
    따로 세고, 같은 앨범/곡의 크레딧 표기 차이(VISUAL ARTS / Key 와 LIA & VISUAL ARTS / Key 등)는
    한 항목으로 합친다. 키는 "대표 아티스트 - 이름". 아티스트 열이면 그대로,
    이름이 비어 있으면 키가 "" (집계에서 제외할 값). 아티스트가 빈 행은 그 이름에서 가장 많이 들은 묶음에 붙인다.
    """
    name = df[column].fillna("").astype(str)
    if column == "artist":
        return name, name
    artist = df["artist"].fillna("").astype(str)

    pairs = pd.DataFrame({"name": name, "artist": artist})[name != ""].groupby(["name", "artist"]).size().rename("n").reset_index()
    named = pairs[pairs["artist"] != ""]
    n_named = named.groupby("name")["artist"].transform("size")

    # 대부분의 이름은 아티스트가 하나뿐이라 묶음 계산이 필요 없다 (그 아티스트가 곧 대표)
    single = named[n_named == 1].set_index("name")["artist"]
    reps = name.map(single)

    # 아티스트 표기가 둘 이상인 이름만 크레딧 묶음 계산
    multi_names = set(named.loc[n_named > 1, "name"])
    if multi_names:
        has_blank = set(pairs.loc[pairs["artist"] == "", "name"])
        rep_of: dict[tuple[str, str], str] = {}
        for nm, grp in named[named["name"].isin(multi_names)].groupby("name"):
            counts = dict(zip(grp["artist"], grp["n"].astype(int)))
            rep = _cluster_artists(counts)
            for a, r in rep.items():
                rep_of[(nm, a)] = r
            if nm in has_blank:
                totals: dict[str, int] = {}
                for a, r in rep.items():
                    totals[r] = totals.get(r, 0) + counts[a]
                rep_of[(nm, "")] = sorted(totals, key=lambda r: (-totals[r], r))[0]
        mask = name.isin(multi_names)
        reps = reps.where(~mask, pd.Series([rep_of.get((n, a), "") for n, a in zip(name[mask], artist[mask])], index=name[mask].index))
    reps = reps.fillna("")
    keys = (reps + " - " + name).where(reps != "", name).where(name != "", "")
    return keys, reps


def key_series(df: pd.DataFrame, column: str) -> pd.Series:
    return resolve_keys(df, column)[0]


def unique_count(df: pd.DataFrame, column: str) -> int:
    keys = key_series(df, column)
    return int(keys[keys != ""].nunique())
