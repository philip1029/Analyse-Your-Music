"""월간 / 주간 청취 기록 분석용 AI 프롬프트 생성.

전체 기간용 build_ai_prompt 와 달리, 선택한 한 달(또는 한 주)을 중심에 두고
"직전 기간"과 비교한 수치 위주로 정리한다. 모든 시각은 한국 시간(KST) 기준이고,
주간은 월요일~일요일이다.
"""

import pandas as pd

from app.analysis.ai_prompt import _sparkline, _table
from app.analysis.diversity import compute_diversity
from app.analysis.library import ranked_page
from app.analysis.listening_time import attach_durations, coverage, fmt_hm, total_seconds
from app.analysis.taste import compute_tag_distribution, load_artist_tags
from app.analysis.trends import classify_region

KST = "Asia/Seoul"
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]
DAYPARTS = [("새벽 (0~6시)", 0, 6), ("오전 (6~12시)", 6, 12), ("오후 (12~18시)", 12, 18), ("저녁·밤 (18~24시)", 18, 24)]
SESSION_GAP = pd.Timedelta(minutes=30)
EARLY_LONG_SESSION_HOURS = 3


def _prep(df: pd.DataFrame) -> pd.DataFrame:
    df = attach_durations(df.copy())      # 행마다 곡 길이(dur_sec): 청취 시간 계산용
    df["datetime_kst"] = pd.to_datetime(df["utc_time"], utc=True, format="mixed").dt.tz_convert(KST)
    df["artist"] = df["artist"].fillna("")
    df["track"] = df["track"].fillna("")
    df["album"] = df["album"].fillna("")
    # 같은 곡명이 여러 아티스트에 있을 수 있어 "아티스트 - 곡명"을 트랙 키로 쓴다.
    df["track_key"] = df.apply(lambda r: f"{r['artist']} - {r['track']}" if r["artist"] else r["track"], axis=1)
    df["album_key"] = df.apply(lambda r: f"{r['album']} ({r['artist']})" if r["artist"] and r["album"] else r["album"], axis=1)
    return df.sort_values("datetime_kst")


def list_periods(df: pd.DataFrame, period: str) -> list[dict]:
    """선택 가능한 기간 목록 (최신순). 월간: 'YYYY-MM', 주간: 그 주 월요일 'YYYY-MM-DD'."""
    dt = pd.to_datetime(df["utc_time"], utc=True, format="mixed").dt.tz_convert(KST)
    if period == "month":
        keys = dt.dt.strftime("%Y-%m")
    elif period == "year":
        keys = dt.dt.strftime("%Y")
    else:
        keys = (dt.dt.normalize() - pd.to_timedelta(dt.dt.dayofweek, unit="D")).dt.strftime("%Y-%m-%d")
    counts = keys.value_counts().sort_index(ascending=False)
    data_edge = dt.max().normalize() + pd.Timedelta(days=1)       # 기록이 닿은 마지막 날의 끝
    data_start = dt.min().normalize()                              # 기록이 시작된 날의 처음
    out = []
    for key, n in counts.items():
        if period == "week":
            start = pd.Timestamp(key, tz=KST)
            end = start + pd.Timedelta(days=7)
            label = f"{key} ~ {(start + pd.Timedelta(days=6)):%m-%d}"
        elif period == "year":
            start = pd.Timestamp(f"{key}-01-01", tz=KST)
            end = start + pd.DateOffset(years=1)
            label = f"{key}년"
        else:
            start = pd.Timestamp(key + "-01", tz=KST)
            end = start + pd.DateOffset(months=1)
            label = key
        # partial: 기록이 이 기간 전체를 덮지 못함(진행 중이거나 데이터 시작/끊김)
        partial = end > data_edge or start < data_start
        out.append({"key": key, "label": label, "scrobbles": int(n), "partial": bool(partial)})
    return out


def _bounds(period: str, anchor: str | None, data_last: pd.Timestamp):
    if period == "month":
        start = pd.Timestamp(anchor + "-01", tz=KST) if anchor else data_last.normalize().replace(day=1)
        end = start + pd.DateOffset(months=1)
        prev_start = start - pd.DateOffset(months=1)
        label = f"{start.year}년 {start.month}월"
    elif period == "year":
        start = pd.Timestamp(f"{anchor}-01-01", tz=KST) if anchor else data_last.normalize().replace(month=1, day=1)
        end = start + pd.DateOffset(years=1)
        prev_start = start - pd.DateOffset(years=1)
        label = f"{start.year}년"
    else:
        day = pd.Timestamp(anchor, tz=KST) if anchor else data_last
        start = day.normalize() - pd.Timedelta(days=day.weekday())
        end = start + pd.Timedelta(days=7)
        prev_start = start - pd.Timedelta(days=7)
        label = f"{start:%Y-%m-%d} ~ {(end - pd.Timedelta(days=1)):%Y-%m-%d}"
    return start, end, prev_start, label


def _pp(value: float) -> str:
    """증감을 %p 로 표기. 반올림해서 0이면 부호 없이 0%p."""
    r = round(value)
    return "0%p" if r == 0 else f"{r:+d}%p"


def _slice(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    return df[(df["datetime_kst"] >= start) & (df["datetime_kst"] < end)]


def _named_counts(df: pd.DataFrame, col: str) -> pd.Series:
    return df[df[col] != ""][col].value_counts()


def _top_compare(cur: pd.DataFrame, prev: pd.DataFrame, before: pd.DataFrame, col: str, n: int = 10,
                 prev_word: str = "직전") -> list[list]:
    c, p = _named_counts(cur, col), _named_counts(prev, col)
    prev_rank = {name: i for i, name in enumerate(p.index, 1)}
    seen_before = set(before[col])
    rows = []
    for i, (name, cnt) in enumerate(c.head(n).items(), 1):
        if name in prev_rank:
            status = f"{prev_word} {prev_rank[name]}위"
        elif name in seen_before:
            status = f"복귀({prev_word} 기간엔 없음)" if prev_word == "직전" else f"복귀({prev_word}엔 없음)"
        else:
            status = "신규(처음 청취)"
        rows.append([i, name, int(cnt), int(p.get(name, 0)) or "-", status])
    return rows


def _first_seen_in(df_all: pd.DataFrame, cur: pd.DataFrame, col: str, start: pd.Timestamp, end: pd.Timestamp):
    valid = df_all[df_all[col] != ""]
    first = valid.groupby(col)["datetime_kst"].min()
    new_names = first[(first >= start) & (first < end)].index
    plays = _named_counts(cur, col)
    new_plays = plays[plays.index.isin(new_names)]
    return len(new_names), new_plays


def _sessions(cur: pd.DataFrame) -> list[dict]:
    if cur.empty:
        return []
    gaps = cur["datetime_kst"].diff()
    sid = (gaps > SESSION_GAP).cumsum()
    out = []
    for _, g in cur.groupby(sid):
        top = g[g["artist"] != ""]["artist"].value_counts()
        out.append(
            {
                "start": g["datetime_kst"].iloc[0],
                "end": g["datetime_kst"].iloc[-1],
                "n": len(g),
                "top_artist": f"{top.index[0]} ({int(top.iloc[0])})" if len(top) else "-",
            }
        )
    return out


def _region_share(df: pd.DataFrame, tag_cache: dict) -> pd.Series:
    if df.empty:
        return pd.Series(dtype=float)
    regions = df["artist"].map(lambda a: classify_region(a, load_artist_tags(a, tag_cache)) if a else "기타")
    return regions.value_counts(normalize=True) * 100


def _tag_shares(df: pd.DataFrame) -> tuple[dict, dict]:
    dist = compute_tag_distribution(df, top_n=500) if not df.empty else {"tags": [], "covered_artists": 0, "total_artists": 0}
    total = sum(t["score"] for t in dist["tags"]) or 1
    return {t["tag"]: t["score"] / total * 100 for t in dist["tags"]}, dist


def _fmt_delta(cur_v: float, prev_v: float | None, suffix: str = "") -> str:
    if prev_v is None:
        return "-"
    d = cur_v - prev_v
    return f"{d:+.1f}{suffix}" if isinstance(d, float) and not float(d).is_integer() else f"{int(d):+d}{suffix}"


def build_period_prompt(df_all: pd.DataFrame, period: str, anchor: str | None = None) -> dict:
    if period not in ("month", "week", "year"):
        raise ValueError("period 는 month, week, year 중 하나여야 합니다.")
    df = _prep(df_all)
    if df.empty:
        raise ValueError("청취 기록이 없습니다.")
    data_first, data_last = df["datetime_kst"].min(), df["datetime_kst"].max()
    try:
        start, end, prev_start, label = _bounds(period, anchor, data_last)
    except Exception as e:  # noqa: BLE001
        raise ValueError(f"anchor 형식이 올바르지 않습니다: {anchor}") from e

    cur, prev = _slice(df, start, end), _slice(df, prev_start, start)
    before = df[df["datetime_kst"] < start]
    if cur.empty:
        raise ValueError(f"{label}에는 청취 기록이 없습니다.")

    if period == "month":
        unit, unit_cap, prev_label = "달", "이번 달", "직전 달"
    elif period == "week":
        unit, unit_cap, prev_label = "주", "이번 주", "직전 주"
    else:  # year: '올해' 대신 실제 연도를 써서, 과거 연도를 고를 때도 헷갈리지 않게 한다
        unit, unit_cap, prev_label = "해", f"{start.year}년", f"전년({prev_start.year}년)"
    total_days = (end - start).days
    covered_days = max(1, (min(end, data_last.normalize() + pd.Timedelta(days=1)) - max(start, data_first.normalize())).days)
    partial = covered_days < total_days
    prev_total_days = (start - prev_start).days
    prev_covered = max(1, (min(start, data_last.normalize() + pd.Timedelta(days=1)) - max(prev_start, data_first.normalize())).days)

    lines: list[str] = []
    title = {"month": "월간", "week": "주간", "year": "연간"}[period]
    particle = "와" if period == "week" else "과"       # 직전 주'와' / 직전 달'과' / 전년(2025년)'과'
    week_note = " 주간은 월요일~일요일 기준입니다." if period == "week" else ""
    lines.append(
        f"당신은 음악 청취 데이터를 분석하는 전문가입니다. 아래는 제 {title} 청취 기록({label})을 "
        f"{prev_label}{particle} 비교해 정리한 수치 데이터입니다 (해석은 최소화하고 계산된 수치/표 위주). "
        f"모든 시각은 한국 시간(KST) 기준입니다.{week_note} 이 데이터를 바탕으로 분석해 주세요.\n"
    )

    # 1. 기간 요약
    lines.append(f"## 1. 기간 요약 ({label})")
    if partial:
        lines.append(
            f"※ 이 기간은 기록이 {data_last:%Y-%m-%d}까지만 있어 {covered_days}/{total_days}일만 포함합니다. "
            f"비교 시 총량이 아니라 '일평균'을 우선해서 봐주세요."
        )
    active_days = cur["datetime_kst"].dt.strftime("%Y-%m-%d").nunique()
    prev_active = prev["datetime_kst"].dt.strftime("%Y-%m-%d").nunique() if len(prev) else 0
    named_art = lambda d: d[d["artist"] != ""]["artist"].nunique()  # noqa: E731
    cur_sec, prev_sec = total_seconds(cur), total_seconds(prev)
    rows = [
        ["총 스크로블", f"{len(cur):,}", f"{len(prev):,}" if len(prev) else "-", _fmt_delta(len(cur), len(prev)) if len(prev) else "-"],
        ["일평균 스크로블", f"{len(cur) / covered_days:.1f}", f"{len(prev) / prev_covered:.1f}" if len(prev) else "-",
         _fmt_delta(round(len(cur) / covered_days, 1), round(len(prev) / prev_covered, 1)) if len(prev) else "-"],
        ["총 청취 시간 (추정)", fmt_hm(cur_sec), fmt_hm(prev_sec) if len(prev) else "-",
         _fmt_delta(round(cur_sec / 3600, 1), round(prev_sec / 3600, 1), "시간") if len(prev) else "-"],
        ["일평균 청취 시간", fmt_hm(cur_sec / covered_days), fmt_hm(prev_sec / prev_covered) if len(prev) else "-",
         _fmt_delta(round(cur_sec / covered_days / 60), round(prev_sec / prev_covered / 60), "분") if len(prev) else "-"],
        ["청취한 날 수", f"{active_days}/{covered_days}", f"{prev_active}/{prev_covered}" if len(prev) else "-",
         _fmt_delta(active_days, prev_active) if len(prev) and not partial and prev_covered >= prev_total_days else "-"],
        ["고유 아티스트", named_art(cur), named_art(prev) if len(prev) else "-", _fmt_delta(named_art(cur), named_art(prev)) if len(prev) else "-"],
        ["고유 트랙", cur["track_key"].nunique(), prev["track_key"].nunique() if len(prev) else "-", _fmt_delta(cur["track_key"].nunique(), prev["track_key"].nunique()) if len(prev) else "-"],
        ["고유 앨범", _named_counts(cur, "album_key").size, _named_counts(prev, "album_key").size if len(prev) else "-",
         _fmt_delta(_named_counts(cur, "album_key").size, _named_counts(prev, "album_key").size) if len(prev) else "-"],
    ]
    lines.append(_table(["항목", unit_cap, prev_label, "증감"], rows))
    empty_artist = int((cur["artist"] == "").sum())
    src = cur["source"].value_counts().to_dict() if "source" in cur else {}
    note = f"- 기록 출처: Apple 재생 로그(A) {src.get('A', 0)}행 / Last.fm(L) {src.get('L', 0)}행"
    if empty_artist:
        note += f" · 아티스트가 비어 있는 {empty_artist}행은 아티스트 통계에서 제외됨"
    lines.append(note)
    lines.append(f"- 청취 시간은 '스크로블 횟수 x 곡 길이'로 계산한 추정치(끝까지 들었다고 가정한 상한)이고, "
                 f"곡 길이를 아는 재생이 {coverage(cur) * 100:.0f}%라 실제보다 조금 적게 잡힐 수 있습니다.")
    if len(prev) and prev_covered < prev_total_days:
        lines.append(f"- 비교 대상({prev_label})은 {prev_covered}/{prev_total_days}일만 기록돼 있어, 총량 증감보다 '일평균'으로 비교해 주세요.")
    if (period == "month" and (start - data_first).days < 90) or (period == "year" and prev_covered < prev_total_days):
        lines.append("- 비교 대상 기간의 기록이 일부뿐(데이터 시작 직후)이라, '신규(처음 청취)' 표시는 실제로는 데이터 시작 전에 들었던 곡일 수 있습니다.")
    lines.append("")

    # 2. 흐름
    lines.append("## 2. 청취량 흐름")
    if period == "week":
        day_rows = []
        for i in range(7):
            d0 = start + pd.Timedelta(days=i)
            day = _slice(cur, d0, d0 + pd.Timedelta(days=1))
            top = _named_counts(day, "artist")
            day_rows.append([f"{d0:%m-%d}({WEEKDAYS[i]})", len(day), fmt_hm(total_seconds(day)),
                             f"{top.index[0]} ({int(top.iloc[0])})" if len(top) else "-"])
        lines.append("### 요일별 (이번 주)")
        lines.append(_table(["날짜", "재생 횟수", "청취 시간", "가장 많이 들은 아티스트"], day_rows))
        trend_periods = [start - pd.Timedelta(days=7 * k) for k in range(7, -1, -1)]
        trend_vals = [len(_slice(df, s, s + pd.Timedelta(days=7))) for s in trend_periods]
        lines.append("")
        lines.append("### 최근 8주 청취량 추이 (오른쪽=이번 주)")
        lines.append(f"추이: {_sparkline(trend_vals)}  값: {trend_vals}")
    elif period == "year":
        first_seen = df[df["artist"] != ""].groupby("artist")["datetime_kst"].min()
        month_rows, month_vals = [], []
        for m in range(12):
            m0 = start + pd.DateOffset(months=m)
            m1 = m0 + pd.DateOffset(months=1)
            if m1 <= data_first or m0 > data_last:
                month_rows.append([f"{m0:%Y-%m}", "-", "-", "-", "기록 없음"])
                month_vals.append(0)
                continue
            part = _slice(cur, m0, m1)
            top = _named_counts(part, "artist")
            new_n = int(((first_seen >= m0) & (first_seen < m1)).sum())
            days_n = part["datetime_kst"].dt.strftime("%Y-%m-%d").nunique()
            month_rows.append([f"{m0:%Y-%m}", len(part), days_n, new_n, f"{top.index[0]} ({int(top.iloc[0])})" if len(top) else "-"])
            month_vals.append(len(part))
        lines.append("### 월별 (1월 → 12월)")
        lines.append(_table(["월", "재생 횟수", "청취한 날 수", "처음 들은 아티스트 수", "가장 많이 들은 아티스트"], month_rows))
        lines.append(f"추이: {_sparkline(month_vals)}  값: {month_vals}  (첫 달/마지막 달은 일부 기간일 수 있음)")
        years = sorted(df["datetime_kst"].dt.year.unique())
        year_vals = [
            len(_slice(df, pd.Timestamp(f"{y}-01-01", tz=KST), pd.Timestamp(f"{y + 1}-01-01", tz=KST))) for y in years
        ]
        lines.append("")
        lines.append("### 연도별 청취량 추이")
        lines.append(
            f"추이: {_sparkline(year_vals)}  " + ", ".join(f"{y}년 {v:,}회" for y, v in zip(years, year_vals))
            + "  (기록이 시작·끝나는 해는 일부 기간일 수 있음)"
        )
        daily = cur.groupby(cur["datetime_kst"].dt.strftime("%Y-%m-%d")).size()
        busiest = daily.sort_values(ascending=False).head(5)
        days = pd.to_datetime(pd.Series(daily.index)).sort_values().reset_index(drop=True)
        streak, best, best_end = 1, 1, days.iloc[0]
        for i in range(1, len(days)):
            streak = streak + 1 if (days.iloc[i] - days.iloc[i - 1]).days == 1 else 1
            if streak > best:
                best, best_end = streak, days.iloc[i]
        lines.append("")
        lines.append("### 연간 하이라이트")
        lines.append("- 가장 많이 들은 날 Top 5: " + ", ".join(f"{d} ({int(n)}회)" for d, n in busiest.items())
                     + " (새벽에 켜 둔 채 잠든 기록이 포함됐을 수 있음)")
        lines.append(f"- 가장 길게 이어진 연속 청취: {best}일 (마지막 날 {best_end:%Y-%m-%d})")
        lines.append(f"- 하루 100회 이상 들은 날: {int((daily >= 100).sum())}일 / 청취한 날 {len(daily)}일")
    else:
        daily = cur.groupby(cur["datetime_kst"].dt.strftime("%Y-%m-%d")).size()
        days_index = [f"{(start + pd.Timedelta(days=i)):%Y-%m-%d}" for i in range(min(total_days, covered_days + max(0, (max(start, data_first.normalize()) - start).days)))]
        daily_vals = [int(daily.get(d, 0)) for d in days_index]
        lines.append("### 일별 청취량 (1일 → " + ("기록의 마지막 날" if partial else "말일") + ")")
        lines.append(f"추이: {_sparkline(daily_vals)}  (최대 {max(daily_vals)}회: {days_index[daily_vals.index(max(daily_vals))]})")
        week_rows = []
        w0 = start - pd.Timedelta(days=start.weekday())
        while w0 < end:
            w1 = w0 + pd.Timedelta(days=7)
            part = _slice(cur, max(w0, start), min(w1, end))
            top = _named_counts(part, "artist")
            week_rows.append([f"{max(w0, start):%m-%d} ~ {(min(w1, end) - pd.Timedelta(days=1)):%m-%d}", len(part),
                              f"{top.index[0]} ({int(top.iloc[0])})" if len(top) else "-"])
            w0 = w1
        lines.append("")
        lines.append("### 주차별")
        lines.append(_table(["주차", "재생 횟수", "가장 많이 들은 아티스트"], week_rows))
        trend_periods = [start - pd.DateOffset(months=k) for k in range(11, -1, -1)]
        trend_vals = [len(_slice(df, s, s + pd.DateOffset(months=1))) for s in trend_periods]
        lines.append("")
        lines.append("### 최근 12개월 청취량 추이 (오른쪽=이번 달)")
        lines.append(f"추이: {_sparkline(trend_vals)}  값: {trend_vals}")
    lines.append("")

    # 3. 순위
    lines.append(f"## 3. 순위 (재생 횟수 기준, {prev_label} 대비)")
    for col, name in [("artist", "아티스트"), ("track_key", "트랙"), ("album_key", "앨범")]:
        lines.append(f"### Top 10 {name}")
        lines.append(_table(["순위", name, unit_cap, prev_label, "상태"],
                            _top_compare(cur, prev, before, col, prev_word="전년" if period == "year" else "직전")))
        lines.append("")

    # 3-2. 청취 시간 기준 순위 (횟수 순위와 다를 수 있다: 긴 곡·긴 앨범이 위로 올라온다)
    lines.append(f"### 청취 시간 기준 Top 5 ({unit_cap})")
    for cat, name in [("artist", "아티스트"), ("track", "트랙"), ("album", "앨범")]:
        page = ranked_page(cur, cat, 0, 5, "time")["items"]
        item_name = lambda it: f"{it['artist']} - {it['name']}" if it.get("artist") and cat != "artist" else it["name"]  # noqa: E731
        lines.append(f"#### {name}")
        lines.append(_table(["순위", name, "청취 시간", "재생 횟수"], [[i, item_name(it), fmt_hm(it["seconds"]), it["count"]] for i, it in enumerate(page, 1)]))
    lines.append("")

    # 4. 신규 발견 / 복귀
    lines.append("## 4. 신규 발견과 복귀")
    n_new_art, new_art_plays = _first_seen_in(df, cur, "artist", start, end)
    n_new_trk, new_trk_plays = _first_seen_in(df, cur, "track_key", start, end)
    lines.append(f"- {unit_cap} 처음 들은 아티스트: {n_new_art}명 / 처음 들은 트랙: {n_new_trk}개 "
                 f"(고유 트랙 대비 {n_new_trk / max(1, cur['track_key'].nunique()) * 100:.0f}%)")
    lines.append("### 처음 들은 아티스트 (재생 횟수순 Top 8)")
    lines.append(_table(["아티스트", "재생 횟수"], [[n, int(c)] for n, c in new_art_plays.head(8).items()]))
    lines.append("")
    lines.append("### 처음 들은 트랙 (재생 횟수순 Top 8)")
    lines.append(_table(["트랙", "재생 횟수"], [[n, int(c)] for n, c in new_trk_plays.head(8).items()]))
    lines.append("")
    cur_art, prev_art = set(_named_counts(cur, "artist").index), set(_named_counts(prev, "artist").index)
    hist_art = set(before[before["artist"] != ""]["artist"])
    returned = sorted((cur_art - prev_art) & hist_art, key=lambda a: -int(_named_counts(cur, "artist").get(a, 0)))
    gone = sorted(prev_art - cur_art, key=lambda a: -int(_named_counts(prev, "artist").get(a, 0)))
    lines.append(f"### {prev_label}엔 없다가 돌아온 아티스트 (Top 8, 재생 횟수순)")
    lines.append(_table(["아티스트", f"{unit_cap} 재생"], [[a, int(_named_counts(cur, 'artist')[a])] for a in returned[:8]]))
    lines.append("")
    lines.append(f"### {prev_label}엔 들었지만 {unit_cap}엔 사라진 아티스트 (Top 8, {prev_label} 재생순)")
    lines.append(_table(["아티스트", f"{prev_label} 재생"], [[a, int(_named_counts(prev, 'artist')[a])] for a in gone[:8]]))
    lines.append("")

    # 5. 시간 패턴
    lines.append("## 5. 시간 패턴")
    hourly = cur["datetime_kst"].dt.hour.value_counts().reindex(range(24), fill_value=0)
    lines.append(f"### 시간대별 (0~23시) 추이: {_sparkline(list(hourly.values))}")
    part_rows = []
    prev_hourly = prev["datetime_kst"].dt.hour.value_counts().reindex(range(24), fill_value=0) if len(prev) else None
    for name, h0, h1 in DAYPARTS:
        c = int(hourly.loc[h0:h1 - 1].sum())
        pc = int(prev_hourly.loc[h0:h1 - 1].sum()) if prev_hourly is not None else None
        part_rows.append([name, c, f"{c / len(cur) * 100:.0f}%", (f"{pc / len(prev) * 100:.0f}%" if pc is not None and len(prev) else "-")])
    lines.append(_table(["시간대", "재생 횟수", f"비중({unit_cap})", f"비중({prev_label})"], part_rows))
    wd = cur["datetime_kst"].dt.dayofweek.value_counts().reindex(range(7), fill_value=0)
    lines.append("")
    lines.append("### 요일별 합계")
    lines.append(_table(["요일", "재생 횟수"], [[WEEKDAYS[i], int(wd[i])] for i in range(7)]))
    lines.append("")

    sess = _sessions(cur)
    lines.append("### 연속 청취 세션 (30분 넘게 끊기면 새 세션)")
    lines.append(f"- 세션 수: {len(sess)}개 · 세션당 평균 {len(cur) / max(1, len(sess)):.1f}곡")
    long_sess = sorted(sess, key=lambda s: -s["n"])[:5]
    srows = []
    for s in long_sess:
        hours = (s["end"] - s["start"]).total_seconds() / 3600
        flag = "새벽 장시간 연속 재생 → 자는 동안 켜져 있던 기록일 수 있음" if s["start"].hour < 6 and hours >= EARLY_LONG_SESSION_HOURS else ""
        srows.append([f"{s['start']:%m-%d %H:%M}~{s['end']:%H:%M}", s["n"], f"{hours:.1f}h", s["top_artist"], flag])
    lines.append(_table(["세션(KST)", "곡 수", "경과", "주요 아티스트(곡 수)", "참고"], srows))
    lines.append("")

    # 6. 장르 / 언어권 / 집중도
    lines.append("## 6. 장르 · 언어권 · 집중도")
    cur_tags, cur_dist = _tag_shares(cur)
    prev_tags, _ = _tag_shares(prev)
    lines.append(f"### 장르/태그 비중 (Last.fm 태그 기준, {cur_dist['covered_artists']}/{cur_dist['total_artists']} 아티스트 반영)")
    if cur_tags:
        trows = [[t, f"{v:.1f}%", f"{prev_tags.get(t, 0):.1f}%" if prev_tags else "-", f"{v - prev_tags.get(t, 0):+.1f}%p" if prev_tags else "-"]  # noqa: E501
                 for t, v in sorted(cur_tags.items(), key=lambda kv: -kv[1])[:8]]
        lines.append(_table(["태그", unit_cap, prev_label, "증감"], trows))
        if prev_tags:
            gain = sorted(((t, cur_tags.get(t, 0) - prev_tags.get(t, 0)) for t in set(cur_tags) | set(prev_tags)), key=lambda x: -x[1])
            lines.append(f"- 비중이 가장 늘어난 태그: " + ", ".join(f"{t}({d:+.1f}%p)" for t, d in gain[:3]))
            lines.append(f"- 비중이 가장 줄어든 태그: " + ", ".join(f"{t}({d:+.1f}%p)" for t, d in gain[-3:][::-1]))
    else:
        lines.append("(태그 캐시 없음 — Taste 탭에서 아티스트 태그를 먼저 조회해야 이 항목이 채워집니다.)")
    lines.append("")

    tag_cache: dict = {}
    reg_cur, reg_prev = _region_share(cur, tag_cache), _region_share(prev, tag_cache)
    lines.append("### 언어/지역권 비중 (아티스트 태그 + 문자 체계 분류)")
    regions = sorted(set(reg_cur.index) | set(reg_prev.index), key=lambda r: -reg_cur.get(r, 0))
    lines.append(_table(["권역", unit_cap, prev_label, "증감"],
                        [[r, f"{reg_cur.get(r, 0):.0f}%", f"{reg_prev.get(r, 0):.0f}%" if len(reg_prev) else "-",
                          _pp(reg_cur.get(r, 0) - reg_prev.get(r, 0)) if len(reg_prev) else "-"] for r in regions]))
    lines.append("")

    d_cur = compute_diversity(cur)
    d_prev = compute_diversity(prev) if len(prev) else None
    div_rows = []
    for key, name in [("artist", "아티스트"), ("track", "트랙")]:
        m = d_cur[key]
        pm = d_prev[key] if d_prev else None
        div_rows.append([name, f"{round(m['normalized_entropy'] * 100)}/100", f"{round(pm['normalized_entropy'] * 100)}/100" if pm else "-",
                         f"{m['top10pct_concentration']}%", f"{pm['top10pct_concentration']}%" if pm else "-",
                         f"{m['most_played']['name']} ({m['most_played']['count']}회)"])
    lines.append("### 다양성 / 집중도")
    lines.append(_table(["구분", f"다양성({unit_cap})", f"다양성({prev_label})", f"상위10% 집중({unit_cap})", f"상위10% 집중({prev_label})", "최다 재생"], div_rows))
    art = _named_counts(cur, "artist")
    if len(art):
        lines.append(f"- 상위 1명 비중 {art.iloc[0] / art.sum() * 100:.0f}% · 상위 3명 비중 {art.head(3).sum() / art.sum() * 100:.0f}%")
    rep = cur["track_key"].value_counts()
    rep_min = 10 if period == "year" else 3        # 한 해는 3번이면 너무 흔해서 기준을 올린다
    rep = rep[rep >= rep_min]
    lines.append("")
    lines.append(f"### {unit_cap} {rep_min}번 이상 반복 재생한 트랙")
    lines.append(_table(["트랙", "재생 횟수"], [[n, int(c)] for n, c in rep.head(8).items()]))
    lines.append("")

    # 분석 요청
    lines.append("## 분석 요청")
    lines.append("위 데이터를 참고해서 다음을 알려주세요:")
    if period == "month":
        asks = [
            f"{label}의 음악 취향을 한두 문단으로 요약하고, 지난달과 달라진 점을 짚어주세요.",
            "순위 표의 '신규/복귀' 표시와 신규 발견 목록을 보고, 이번 달의 새로운 관심사가 무엇이었는지 분석해 주세요.",
            "주차별 흐름과 일별 추이를 보고, 이번 달 청취 리듬(몰아 들은 시기, 뜸했던 시기)과 그 원인으로 짐작되는 것을 말해 주세요.",
            "시간대·세션 데이터를 보고 청취 습관(언제, 얼마나 길게)에 대해 알려주세요. 새벽 장시간 재생은 자는 동안 켜져 있던 것일 수 있으니 감안해 주세요.",
            "다음 달에 들어보면 좋을 아티스트/앨범을 3~5개 추천해 주세요 (이번 달 신규 발견과 비중이 늘어난 장르를 근거로).",
        ]
    elif period == "year":
        asks = [
            f"{label} 한 해의 음악 취향을 한두 문단으로 요약하고, {prev_label}과 달라진 점을 짚어주세요.",
            "월별 표와 12개월 추이를 보고, 한 해의 흐름(몰두한 시기, 뜸했던 시기)과 그 계기로 짐작되는 것을 설명해 주세요.",
            "연간 Top 10(아티스트/트랙/앨범)과 신규 발견·복귀 목록을 보고, 이 해의 '키워드' 3개를 뽑아 한 줄씩 설명해 주세요.",
            "장르·언어권 비중 변화에서 취향이 크게 이동했는지 분석하고, 시간대·세션 데이터로 청취 습관이 달라졌는지 짚어주세요. 새벽 장시간 재생은 자는 동안 켜져 있던 것일 수 있으니 감안해 주세요.",
            "다음 해에 파볼 만한 장르·아티스트·앨범을 5개 추천해 주세요 (이 해의 신규 발견과 비중이 늘어난 장르를 근거로).",
        ]
    else:
        asks = [
            f"{label} 한 주의 청취를 한두 문단으로 요약해 주세요.",
            "요일별 표를 보고, 이번 주 어느 날 어떤 음악을 어떻게 들었는지 하루하루의 특징을 짧게 정리해 주세요.",
            "지난주 대비 늘어난/줄어든 아티스트와 장르를 짚고, 한 주 사이의 취향 이동이 있었는지 분석해 주세요.",
            "시간대·세션 데이터에서 눈에 띄는 습관이나 이상한 점(새벽 장시간 재생 등)이 있으면 알려주세요.",
            "다음 주에 들어보면 좋을 음악이나 이어서 파볼 만한 아티스트를 2~3개 추천해 주세요.",
        ]
    for i, a in enumerate(asks, 1):
        lines.append(f"{i}. {a}")

    return {
        "prompt": "\n".join(lines),
        "meta": {
            "period": period,
            "label": label,
            "start": f"{start:%Y-%m-%d}",
            "end": f"{(end - pd.Timedelta(days=1)):%Y-%m-%d}",
            "scrobbles": int(len(cur)),
            "partial": bool(partial),
        },
    }
