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


def name_key(name: str) -> str:
    """이름 비교용 정규화: NFKC, 소문자, 글자·숫자만 남김 (글자·숫자가 없는 이름은 소문자 원문)."""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", name).lower()) or name.casefold()


def resolve_all(df: pd.DataFrame, column: str) -> tuple[pd.Series, pd.Series, pd.Series]:
    """
    집계용 (키, 대표 아티스트, 표시 이름). 곡명·앨범명만 같은 다른 아티스트의 항목(Untitled, Eureka, Romance 등)은
    따로 세고, 같은 앨범/곡의 크레딧 표기 차이(VISUAL ARTS / Key 와 LIA & VISUAL ARTS / Key 등)와
    대소문자·띄어쓰기만 다른 제목(Tori no Uta / Tori no uta)은 한 항목으로 합친다.
    키는 "대표 아티스트 - 표시 이름"이고 표시 이름은 가장 많이 쓰인 표기다. 아티스트 열이면 그대로,
    이름이 비어 있으면 키가 "" (집계에서 제외할 값). 아티스트가 빈 행은 그 이름에서 가장 많이 들은 묶음에 붙인다.
    """
    name = df[column].fillna("").astype(str)
    if column == "artist":
        return name, name, name
    artist = df["artist"].fillna("").astype(str)
    present = name != ""

    nk = name.map({n: name_key(n) for n in pd.unique(name[present])}).fillna("")
    pairs = pd.DataFrame({"nk": nk, "name": name, "artist": artist})[present]

    # 같은 이름(대소문자·띄어쓰기 무시)의 표시 표기: 가장 많이 쓰인 것
    spell = (
        pairs.groupby(["nk", "name"]).size().reset_index(name="n")
        .sort_values(["n", "name"], ascending=[False, True]).drop_duplicates("nk").set_index("nk")["name"]
    )
    names = nk.map(spell).fillna("")

    art = pairs.groupby(["nk", "artist"]).size().rename("n").reset_index()
    named = art[art["artist"] != ""]
    n_named = named.groupby("nk")["artist"].transform("size")

    # 대부분의 이름은 아티스트가 하나뿐이라 묶음 계산이 필요 없다 (그 아티스트가 곧 대표)
    single = named[n_named == 1].set_index("nk")["artist"]
    reps = nk.map(single)

    # 아티스트 표기가 둘 이상인 이름만 크레딧 묶음 계산
    multi = set(named.loc[n_named > 1, "nk"])
    if multi:
        has_blank = set(art.loc[art["artist"] == "", "nk"])
        rep_of: dict[tuple[str, str], str] = {}
        for k, grp in named[named["nk"].isin(multi)].groupby("nk"):
            counts = dict(zip(grp["artist"], grp["n"].astype(int)))
            rep = _cluster_artists(counts)
            for a, r in rep.items():
                rep_of[(k, a)] = r
            if k in has_blank:
                totals: dict[str, int] = {}
                for a, r in rep.items():
                    totals[r] = totals.get(r, 0) + counts[a]
                rep_of[(k, "")] = sorted(totals, key=lambda r: (-totals[r], r))[0]
        mask = nk.isin(multi)
        reps = reps.where(~mask, pd.Series([rep_of.get((k, a), "") for k, a in zip(nk[mask], artist[mask])], index=nk[mask].index))
    reps = reps.fillna("")

    keys = (reps + " - " + names).where(reps != "", names).where(names != "", "")
    return keys, reps, names


def resolve_keys(df: pd.DataFrame, column: str) -> tuple[pd.Series, pd.Series]:
    keys, reps, _ = resolve_all(df, column)
    return keys, reps


def key_series(df: pd.DataFrame, column: str) -> pd.Series:
    return resolve_all(df, column)[0]


def unique_count(df: pd.DataFrame, column: str) -> int:
    keys = key_series(df, column)
    return int(keys[keys != ""].nunique())
