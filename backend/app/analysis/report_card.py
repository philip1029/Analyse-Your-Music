"""공유용 리포트 카드 데이터: 한 기간(주·월·연·전체)의 요약, 순위, 시간대별 청취량."""

import pandas as pd

from app.analysis.ai_prompt_period import KST, _bounds, _prep, _slice
from app.analysis.keys import unique_count
from app.analysis.library import ranked_page
from app.analysis.listening_time import total_seconds, weights
from app.analysis.taste import compute_tag_distribution

TOP_N = 5


def _range_text(first: pd.Timestamp, last: pd.Timestamp) -> str:
    return f"{first:%Y.%m.%d} – {last:%Y.%m.%d}"


def build_report_card(df_all: pd.DataFrame, period: str, anchor: str | None = None, username: str | None = None) -> dict:
    if period not in ("week", "month", "year", "all"):
        raise ValueError("period 는 week, month, year, all 중 하나여야 합니다.")
    df = _prep(df_all)
    if df.empty:
        raise ValueError("청취 기록이 없습니다.")
    data_first, data_last = df["datetime_kst"].min(), df["datetime_kst"].max()

    if period == "all":
        start, end, label = data_first.normalize(), data_last.normalize() + pd.Timedelta(days=1), "전체 기간"
    else:
        start, end, _, label = _bounds(period, anchor, data_last)
    cur = _slice(df, start, end)
    if cur.empty:
        raise ValueError(f"{label}에는 청취 기록이 없습니다.")

    # 기간 표기는 실제 기록이 닿은 날까지만 (진행 중이거나 데이터가 시작되기 전인 날은 제외)
    shown_first = max(start, data_first.normalize())
    shown_last = min(end - pd.Timedelta(days=1), data_last.normalize())

    named = cur[cur["artist"] != ""]
    tops = {}
    for cat in ("artist", "album", "track"):
        tops[cat] = {
            "plays": ranked_page(cur, cat, 0, TOP_N, "plays")["items"],
            "time": ranked_page(cur, cat, 0, TOP_N, "time")["items"],
        }

    tags = [t["tag"] for t in compute_tag_distribution(named, top_n=TOP_N)["tags"]] if len(named) else []

    day = cur["datetime_kst"].dt.strftime("%Y-%m-%d")
    per_day = weights(cur, "time").groupby(day).sum() * 60          # 초
    plays_per_day = day.groupby(day).size()
    busiest = per_day.idxmax()
    hours = cur["datetime_kst"].dt.hour
    return {
        "username": username,
        "period": period,
        "label": label,
        "range_text": _range_text(shown_first, shown_last),
        "start": f"{shown_first:%Y-%m-%d}",
        "end": f"{shown_last:%Y-%m-%d}",
        "scrobbles": int(len(cur)),
        "seconds": total_seconds(cur),
        "artists": int(named["artist"].nunique()),
        "albums": unique_count(cur, "album"),
        "tracks": unique_count(cur, "track"),
        "tags": tags,
        "tops": tops,
        "busiest_day": {"date": busiest, "seconds": int(per_day[busiest]), "plays": int(plays_per_day[busiest])},
        "hourly_plays": [int(x) for x in hours.value_counts().reindex(range(24), fill_value=0)],
        "hourly_minutes": [round(float(x), 1) for x in weights(cur, "time").groupby(hours).sum().reindex(range(24), fill_value=0)],
    }
