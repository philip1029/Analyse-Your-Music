import math

import numpy as np
import pandas as pd

from app.analysis.keys import resolve_keys
from app.analysis.library import durations

# 월 단위로 나눠서 "한 시기에 몰아 들었는지, 꾸준히 들었는지"를 본다.
#  - 구간: 그 항목을 처음 들은 달 ~ 데이터의 마지막 달 (아직 모르던 시기는 제외, 이후 안 들은 시기는 포함)
#  - evenness(고름): 월별 재생 비율의 정규화 엔트로피. 1이면 모든 달에 똑같이, 0이면 한 달에 전부 몰림
#  - bias(편향도) = 1 - evenness
DEFAULT_MIN_PLAYS = 20
DEFAULT_MIN_MONTHS = 12


def _month_index(df: pd.DataFrame) -> pd.Series:
    """KST 기준 월 번호 (연*12+월-1)."""
    kst = pd.to_datetime(df["utc_time"], utc=True, format="mixed").dt.tz_convert("Asia/Seoul")
    return kst.dt.year * 12 + kst.dt.month - 1


def _labels(first_idx: int, last_idx: int) -> list[str]:
    return [f"{i // 12}-{i % 12 + 1:02d}" for i in range(first_idx, last_idx + 1)]


def _stats(counts: np.ndarray, labels: list[str]) -> dict | None:
    """counts: 데이터 전체 월 구간에 대한 월별 재생 수."""
    nz_idx = np.nonzero(counts)[0]
    if len(nz_idx) == 0:
        return None
    first, last = int(nz_idx[0]), int(nz_idx[-1])
    window = counts[first:]
    months = len(window)
    total = int(window.sum())
    p = window[window > 0] / total
    entropy = float(-(p * np.log2(p)).sum())
    evenness = round(entropy / math.log2(months) + 0.0, 3) if months > 1 else None   # +0.0: -0.0 방지
    peak = int(np.argmax(counts))
    return {
        "plays": total,
        "first_month": labels[first],
        "last_month": labels[last],
        "months": months,                               # 처음 들은 달부터 지금까지의 달 수
        "active_months": int(len(nz_idx)),              # 그중 한 번이라도 들은 달 수
        "months_since_last": len(labels) - 1 - last,    # 마지막으로 들은 뒤 지난 달 수
        "evenness": evenness,
        "bias": round(1 - evenness + 0.0, 3) if evenness is not None else None,
        "peak_month": labels[peak],
        "peak_share": round(float(counts[peak]) / total, 3),
        "monthly": [int(c) for c in counts],
    }


def _monthly_matrix(df: pd.DataFrame, category: str):
    """(키 -> 월별 재생 수 배열) 과 월 라벨 목록."""
    keys, reps = resolve_keys(df, category)
    valid = keys != ""
    months = _month_index(df)
    first_idx, last_idx = int(months.min()), int(months.max())
    labels = _labels(first_idx, last_idx)
    counts = pd.DataFrame({"key": keys[valid], "m": months[valid] - first_idx}).groupby(["key", "m"]).size().unstack(fill_value=0)
    counts = counts.reindex(columns=range(len(labels)), fill_value=0)
    return counts, labels, keys, reps, valid


def stats_for_keys(df: pd.DataFrame, category: str, wanted_keys: list[str]) -> tuple[dict, list[str]]:
    """Top 목록처럼 이미 정해진 항목들의 월별 통계. 반환: ({키: 통계}, 월 라벨)."""
    if len(df) == 0:
        return {}, []
    counts, labels, _, _, _ = _monthly_matrix(df, category)
    out = {}
    for k in wanted_keys:
        if k in counts.index:
            st = _stats(counts.loc[k].to_numpy(), labels)
            if st:
                out[k] = st
    return out, labels


def compute_consistency(
    df: pd.DataFrame,
    category: str = "track",
    min_plays: int = DEFAULT_MIN_PLAYS,
    min_months: int = DEFAULT_MIN_MONTHS,
    limit: int = 50,
    sort: str = "even",
) -> dict:
    """꾸준히(고르게) 들은 순 또는 한 시기에 몰아 들은 순으로 항목을 정렬한다."""
    criteria = {"min_plays": min_plays, "min_months": min_months}
    if len(df) == 0:
        return {"category": category, "months": [], "criteria": criteria, "total_candidates": 0, "results": []}
    counts, labels, keys, reps, valid = _monthly_matrix(df, category)

    # 표시용 이름·아티스트: 항목의 첫 기록에서 가져온다
    meta = df[valid].assign(_key=keys[valid], _rep=reps[valid]).drop_duplicates("_key").set_index("_key")
    rows = []
    for key in counts.index[counts.sum(axis=1) >= min_plays]:
        st = _stats(counts.loc[key].to_numpy(), labels)
        if not st or st["months"] < min_months or st["evenness"] is None:
            continue
        row = meta.loc[key]
        artist = (row["_rep"] or None) if category != "artist" else None
        rows.append({"key": key, "name": row[category], "artist": artist, **st})

    rows.sort(key=lambda r: (-r["evenness"] if sort == "even" else r["evenness"], -r["plays"], r["key"]))
    total = len(rows)
    rows = rows[:limit]
    if category == "track" and rows:
        # 표지용: 결과에 든 곡만, 가장 많이 기록된 앨범 (전체 곡에 대해 계산하면 느리다)
        picked = {r["key"] for r in rows}
        has_album = keys.isin(picked) & df["album"].notna() & (df["album"] != "")
        if has_album.any():
            top_album = df[has_album].assign(_key=keys[has_album]).groupby(["_key", "album"]).size().reset_index(name="n")
            top_album = top_album.sort_values(["n", "album"], ascending=[False, True]).drop_duplicates("_key").set_index("_key")["album"]
            for r in rows:
                r["album"] = top_album.get(r["key"])
        for r in rows:
            r["duration"] = durations.get(r["artist"] or "", r["name"])
    return {"category": category, "months": labels, "criteria": criteria, "total_candidates": total, "results": rows}
