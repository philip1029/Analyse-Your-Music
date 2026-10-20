"""
청취 시간: 스크롭 횟수 x 곡 길이.

스크롭은 "끝까지 들었다"고 가정한 추정치(상한)다 (중간에 넘긴 곡도 한 곡으로 센다).
길이를 모르는 곡은 시간 0으로 더하고 coverage(길이를 아는 재생의 비율)로 함께 보여 준다.
MIN_TRACK_SEC 미만으로 나온 길이는 Last.fm 값이 틀렸을 가능성이 커서 모르는 것으로 본다.
"""

import pandas as pd

from app.analysis.duration_store import durations

MIN_TRACK_SEC = 10


def attach_durations(df: pd.DataFrame) -> pd.DataFrame:
    """행마다 곡 길이(초)를 dur_sec 열로 붙인다. 모르면 NaN."""
    if "dur_sec" in df.columns:
        return df
    if len(df) == 0:
        return df.assign(dur_sec=pd.Series(dtype=float))
    artist = df["artist"].fillna("").astype(str)
    track = df["track"].fillna("").astype(str)
    pairs = pd.DataFrame({"a": artist, "t": track}).drop_duplicates()
    secs = durations.get_many([(a, t) for a, t in zip(pairs["a"], pairs["t"]) if t])
    values = [secs.get((a, t)) for a, t in zip(artist, track)]
    dur = pd.Series(values, index=df.index, dtype="float64")
    return df.assign(dur_sec=dur.where(dur >= MIN_TRACK_SEC))


def weights(df: pd.DataFrame, metric: str) -> pd.Series:
    """metric == "time" 이면 행마다 분(길이를 모르면 0), 아니면 1 (횟수)."""
    if metric == "time":
        return attach_durations(df)["dur_sec"].fillna(0) / 60.0
    return pd.Series(1.0, index=df.index)


def total_seconds(df: pd.DataFrame) -> int:
    return int(attach_durations(df)["dur_sec"].fillna(0).sum())


def coverage(df: pd.DataFrame) -> float:
    """길이를 아는 재생의 비율 (0~1)."""
    if len(df) == 0:
        return 0.0
    return float(attach_durations(df)["dur_sec"].notna().mean())


def _kst_date(df: pd.DataFrame) -> pd.Series:
    kst = pd.to_datetime(df["utc_time"], utc=True, format="mixed").dt.tz_convert("Asia/Seoul")
    return kst.dt.strftime("%Y-%m-%d")


def time_summary(df: pd.DataFrame) -> dict:
    """전체 청취 시간, 하루 평균, 가장 많이 들은 날."""
    if len(df) == 0:
        return {"total_seconds": 0, "known_plays": 0, "total_plays": 0, "coverage": 0.0, "days": 0, "active_days": 0,
                "avg_seconds_per_day": 0, "avg_seconds_per_active_day": 0, "busiest_day": None}
    d = attach_durations(df)
    day = _kst_date(d)
    per_day = d["dur_sec"].fillna(0).groupby(day).sum()
    plays_per_day = day.groupby(day).size()
    total = int(per_day.sum())
    first, last = pd.Timestamp(day.min()), pd.Timestamp(day.max())
    days = (last - first).days + 1
    busiest = per_day.idxmax()
    return {
        "total_seconds": total,
        "known_plays": int(d["dur_sec"].notna().sum()),
        "total_plays": int(len(d)),
        "coverage": round(float(d["dur_sec"].notna().mean()), 4),
        "days": int(days),
        "active_days": int(len(per_day)),
        "avg_seconds_per_day": int(total / days),
        "avg_seconds_per_active_day": int(total / len(per_day)),
        "busiest_day": {"date": busiest, "seconds": int(per_day[busiest]), "plays": int(plays_per_day[busiest])},
    }


def fmt_hm(seconds: float) -> str:
    """초 -> '12시간 5분' (1시간 미만이면 '35분')."""
    minutes = int(round(seconds / 60))
    h, m = divmod(minutes, 60)
    return f"{h}시간 {m}분" if h else f"{m}분"
