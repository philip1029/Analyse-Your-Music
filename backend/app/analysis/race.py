"""
Bar chart race: 시간이 흐르면서 누적 재생 순위가 바뀌는 모습을 그리기 위한 데이터.

기간(월·주·일)마다 값을 개체(아티스트·앨범·트랙·태그)별로 돌려준다. 기본은 "그 기간 끝까지의 누적 값"이고, window(일)를 주면
"그 기간 끝까지 최근 window 일 동안의 값"(롤링)이다. 일 단위로 보면 30일 롤링 순위가 하루씩 착착 바뀐다. 화면이 기간 사이를 보간해 막대가 부드럽게
자라고 순위가 바뀌게 그린다. 모든 개체를 주면 너무 많으므로, 어느 기간에든 상위 top_n 안에 든 개체의 합집합만 준다 (최대 max_entities).
앨범·트랙은 앱의 다른 화면과 같은 방식(resolve_all)으로 센다. 태그는 캐시에 있는 아티스트 태그(상위 5개)를 재생 수로 가중해 합친다 (캐시에 없는
아티스트는 빠지므로 반영 비율을 같이 돌려준다). 모든 기준은 한국 시간(KST)이다.
"""

import json

import numpy as np
import pandas as pd

from app.analysis import taste
from app.analysis.keys import resolve_all

CATS = ("artist", "album", "track", "tag")
STEPS = {"month": "M", "week": "W-SUN", "day": "D"}
MAX_WINDOW = 365


def _periods(df: pd.DataFrame, step: str):
    """(행별 기간 번호 Series, 기간 목록 [{"label", "date"}]) — 첫 기간부터 마지막 기간까지 빈 기간도 이어서 만든다."""
    kst = pd.to_datetime(pd.to_numeric(df["uts"], errors="coerce"), unit="s", utc=True).dt.tz_convert("Asia/Seoul").dt.tz_localize(None)
    per = kst.dt.to_period(STEPS[step])
    first = per.min()
    idx = (per.map(lambda p: p.ordinal) - first.ordinal).astype(int)
    count = int(idx.max()) + 1
    periods = []
    for i in range(count):
        p = first + i
        day = p.start_time.strftime("%Y-%m-%d")
        periods.append({"label": p.strftime("%Y-%m") if step == "month" else day, "date": day})
    return idx, periods


def _cumulative(keys: pd.Series, idx: pd.Series, count: int) -> pd.DataFrame:
    """행 = 개체 키, 열 = 기간 번호, 값 = 그 기간 끝까지의 누적 재생 수."""
    valid = keys != ""
    table = pd.DataFrame({"key": keys[valid], "p": idx[valid]}).groupby(["key", "p"]).size().unstack(fill_value=0)
    table = table.reindex(columns=range(count), fill_value=0)
    return table.cumsum(axis=1)


def _tag_series(artist_values: pd.DataFrame, artist_totals: pd.Series) -> tuple[pd.DataFrame, float]:
    """아티스트별 값(누적 또는 롤링) -> 태그별 점수 (캐시에 있는 태그 상위 5개, 가중치 = count / 100). 반영 비율은 전체 재생(artist_totals) 기준."""
    rows: dict[str, np.ndarray] = {}
    covered = 0
    for artist, values in artist_values.iterrows():
        path = taste.CACHE_DIR / f"{taste._slugify(taste.resolve_artist_name(artist))}.json"
        if not path.exists():
            continue
        try:
            tags = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        covered += int(artist_totals[artist])
        for tag in tags[:5]:
            name = str(tag.get("name", "")).lower()
            if name:
                rows[name] = rows.get(name, 0) + values.to_numpy(dtype=float) * (tag.get("count", 0) / 100)
    total = int(artist_totals.sum()) if len(artist_totals) else 0
    table = pd.DataFrame(rows, index=artist_values.columns).T if rows else pd.DataFrame(columns=artist_values.columns)
    return table, (covered / total if total else 0.0)


def build_race(df: pd.DataFrame, cat: str = "artist", step: str = "month", top_n: int = 10, max_entities: int = 80, window: int = 0) -> dict:
    if cat not in CATS:
        return {"error": f"cat 은 {', '.join(CATS)} 중 하나여야 합니다."}
    if step not in STEPS:
        return {"error": f"step 은 {', '.join(STEPS)} 중 하나여야 합니다."}
    top_n = max(1, min(int(top_n), 20))
    window = max(0, min(int(window), MAX_WINDOW))             # 0 = 누적, 그 외 = 최근 window 일
    empty = {"cat": cat, "step": step, "window": window, "periods": [], "entities": [], "total_plays": 0, "coverage": None}
    if df is None or len(df) == 0 or "uts" not in df.columns:
        return empty
    df = df.reset_index(drop=True)
    idx, periods = _periods(df, step)
    count = len(periods)

    def windowed(cumulative: pd.DataFrame) -> pd.DataFrame:
        """누적 표 -> 롤링 표: 각 기간 끝까지 최근 window 기간(일 단위면 window 일)의 값. window 가 0 이면 누적 그대로."""
        if not window:
            return cumulative
        return cumulative - cumulative.shift(window, axis=1, fill_value=0)

    artist_of: dict[str, str | None] = {}
    name_of: dict[str, str] = {}
    coverage = None
    if cat == "artist":
        keys = df["artist"].fillna("").astype(str)
        cum = windowed(_cumulative(keys, idx, count))
        name_of = {k: k for k in cum.index}
    elif cat in ("album", "track"):
        keys, reps, names = resolve_all(df, cat)
        cum = windowed(_cumulative(keys, idx, count))
        first = pd.DataFrame({"key": keys, "artist": reps, "name": names}).drop_duplicates("key").set_index("key")
        artist_of = {k: (first.at[k, "artist"] or None) for k in cum.index}
        name_of = {k: first.at[k, "name"] for k in cum.index}
    else:
        artists = df["artist"].fillna("").astype(str)
        artist_cum = _cumulative(artists, idx, count)
        cum, coverage = _tag_series(windowed(artist_cum), artist_cum.iloc[:, -1] if len(artist_cum) else pd.Series(dtype=int))
        name_of = {k: k for k in cum.index}

    if cum.empty:
        return {**empty, "periods": periods, "coverage": coverage}

    # 어느 기간에든 상위 top_n 에 든 개체의 합집합 (기간 순서대로 모아서, 많으면 마지막 값이 큰 순으로 자른다)
    names = list(cum.index)
    matrix = cum.to_numpy(dtype=float)
    chosen: dict[str, None] = {}
    for p in range(count):
        col = matrix[:, p]
        for i in np.argsort(-col, kind="stable")[:top_n]:
            if col[i] > 0:
                chosen[names[i]] = None
    # 자를 때는 가장 높이 올라간 값이 큰 개체를 남긴다 (롤링에서는 마지막 값이 아니라 최고 값이 기준이다)
    peak = {k: float(matrix[names.index(k)].max()) for k in chosen}
    keep = sorted(chosen, key=lambda k: (-peak[k], k))[:max_entities]

    entities = [
        {"key": k, "name": name_of[k], "artist": artist_of.get(k), "values": [round(float(v), 1) if cat == "tag" else int(v) for v in cum.loc[k].to_numpy()]}
        for k in keep
    ]
    return {"cat": cat, "step": step, "window": window, "top_n": top_n, "periods": periods, "entities": entities, "total_plays": int(len(df)), "coverage": coverage}
