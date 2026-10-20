"""Overview 통계 카드(스크로블·아티스트·앨범·트랙)의 값, 직전 같은 기간 대비 증감, 미니 막대 데이터."""

import pandas as pd

from app.analysis.keys import key_series

RECENT_DAYS = 30          # 전체 기간 보기에서 증감을 보여 줄 "최근" 구간 길이
BARS = 6                  # 미니 막대 개수


def _kst_dates(df: pd.DataFrame) -> pd.Series:
    kst = pd.to_datetime(df["utc_time"], utc=True, format="mixed").dt.tz_convert("Asia/Seoul")
    return kst.dt.strftime("%Y-%m-%d")


class _Counter:
    """곡·앨범 키를 전체 데이터에 대해 한 번만 계산해 두고, 기간별 고유 개수는 마스크로 센다 (기간마다 다시 계산하면 느리다)."""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.artist = df["artist"].fillna("").astype(str)
        self.album = key_series(df, "album")
        self.track = key_series(df, "track")

    def metrics(self, mask: pd.Series) -> dict:
        if not mask.any():
            return {"scrobbles": 0, "artists": 0, "albums": 0, "tracks": 0}
        a, al, t = self.artist[mask], self.album[mask], self.track[mask]
        return {
            "scrobbles": int(mask.sum()),
            "artists": int(a[a != ""].nunique()),
            "albums": int(al[al != ""].nunique()),
            "tracks": int(t[t != ""].nunique()),
        }


def _window(dates: pd.Series, first: str, last: str) -> pd.Series:
    return (dates >= first) & (dates <= last)


def _day(s: str) -> pd.Timestamp:
    return pd.Timestamp(s)


def _delta_pct(cur: float, prev: float) -> float | None:
    return None if prev <= 0 else round((cur - prev) / prev * 100, 1)


def build_overview_cards(df: pd.DataFrame, start: str | None = None, end: str | None = None) -> dict:
    """
    start/end 가 있으면: 그 기간(KST 날짜, 양 끝 포함) 값 vs 바로 앞의 같은 길이 기간 (mode="range").
    둘 다 없으면: 전체 기간 값을 보여 주고, 증감은 최근 30일 vs 그 직전 30일 (mode="recent").
    미니 막대는 기간을 6등분(전체 기간이면 최근 6개월)한 각 구간의 값이다.
    """
    if len(df) == 0:
        return {"mode": "range", "label": "", "delta_label": "", "cards": {}}
    dates = _kst_dates(df)
    counter = _Counter(df)
    empty = pd.Series(False, index=df.index)
    data_first, data_last = dates.min(), dates.max()

    if start or end:
        first, last = start or data_first, end or data_last
        last = min(last, data_last) if last > data_last else last
        n_days = (_day(last) - _day(first)).days + 1
        cur = _window(dates, first, last)
        prev_first = (_day(first) - pd.Timedelta(days=n_days)).strftime("%Y-%m-%d")
        prev_last = (_day(first) - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        prev = _window(dates, prev_first, prev_last) if prev_last >= data_first else empty
        shown = cmp_cur = counter.metrics(cur)
        cmp_prev = counter.metrics(prev)
        mode, label, delta_label = "range", f"{first} ~ {last}", "직전 같은 기간 대비"
        edges = [(_day(first) + pd.Timedelta(days=round(n_days * i / BARS))) for i in range(BARS + 1)]
        slices = [(edges[i].strftime("%Y-%m-%d"), (edges[i + 1] - pd.Timedelta(days=1)).strftime("%Y-%m-%d")) for i in range(BARS)]
    else:
        last_day = _day(data_last)
        cur_first = (last_day - pd.Timedelta(days=RECENT_DAYS - 1)).strftime("%Y-%m-%d")
        prev_first = (last_day - pd.Timedelta(days=2 * RECENT_DAYS - 1)).strftime("%Y-%m-%d")
        prev_last = (last_day - pd.Timedelta(days=RECENT_DAYS)).strftime("%Y-%m-%d")
        shown = counter.metrics(pd.Series(True, index=df.index))
        cmp_cur = counter.metrics(_window(dates, cur_first, data_last))
        cmp_prev = counter.metrics(_window(dates, prev_first, prev_last)) if prev_last >= data_first else counter.metrics(empty)
        mode, label, delta_label = "recent", f"{data_first} ~ {data_last}", f"최근 {RECENT_DAYS}일 · 직전 {RECENT_DAYS}일 대비"
        months = pd.period_range(end=last_day.to_period("M"), periods=BARS, freq="M")
        slices = [(m.start_time.strftime("%Y-%m-%d"), m.end_time.strftime("%Y-%m-%d")) for m in months]

    bar_metrics = [counter.metrics(_window(dates, a, b)) for a, b in slices]
    cards = {}
    for key in ("scrobbles", "artists", "albums", "tracks"):
        cards[key] = {
            "value": shown[key],
            "delta_pct": _delta_pct(cmp_cur[key], cmp_prev[key]),
            "prev": cmp_prev[key],
            "bars": [m[key] for m in bar_metrics],
        }
    return {"mode": mode, "label": label, "delta_label": delta_label, "cards": cards}
