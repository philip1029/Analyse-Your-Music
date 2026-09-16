import re
import pandas as pd
from app.analysis.taste import load_artist_tags

_HANGUL_RE = re.compile(r"[가-힣ᄀ-ᇿ㄰-㆏]")
_KANA_RE = re.compile(r"[぀-ヿ]")
_CJK_RE = re.compile(r"[一-鿿]")
_LATIN_RE = re.compile(r"[A-Za-z]")


_JAPAN_TAG_HINTS = {"japanese", "j-pop", "j-rock", "jpop", "jrock", "anime", "vocaloid", "japan"}
_KOREA_TAG_HINTS = {"korean", "k-pop", "kpop", "korea"}


def classify_region(artist_name: str, tags: list | None = None) -> str:
    """
    아티스트를 권역으로 분류한다.
    1차: Last.fm 태그 캐시에 japanese/korean 계열 태그가 있으면 그걸 우선 사용
        (로마자로 표기된 일본/한국 아티스트명을 문자 체계만으로는 구분 못 하는 문제 보완)
    2차: 태그 정보가 없으면 아티스트명의 문자 체계(한글/가나/한자/라틴)로 분류
    """
    if tags:
        tag_names = {t["name"].lower() for t in tags[:5]}
        if tag_names & _JAPAN_TAG_HINTS:
            return "일본어권"
        if tag_names & _KOREA_TAG_HINTS:
            return "한국어권"

    if not isinstance(artist_name, str) or not artist_name.strip():
        return "기타"
    if _HANGUL_RE.search(artist_name):
        return "한국어권"
    if _KANA_RE.search(artist_name):
        return "일본어권"
    if _CJK_RE.search(artist_name):
        return "기타"
    if _LATIN_RE.search(artist_name):
        return "영어권"
    return "기타"


def _with_kst(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True, format="mixed")
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    return df


def compute_region_trend(df: pd.DataFrame, recent_months: int = 3) -> dict:
    """월별 권역(언어권)별 재생 비중(%) 추이와, 최근 N개월 vs 그 이전 평균 비교."""
    df = _with_kst(df)

    tag_cache: dict[str, list] = {}
    region_by_artist = {
        artist: classify_region(artist, load_artist_tags(artist, tag_cache))
        for artist in df["artist"].unique()
    }
    df["region"] = df["artist"].map(region_by_artist)
    df["year_month"] = df["datetime_kst"].dt.strftime("%Y-%m")

    periods = sorted(df["year_month"].unique())
    monthly_total = df.groupby("year_month").size()
    monthly_region = df.groupby(["year_month", "region"]).size().unstack(fill_value=0)
    monthly_pct = monthly_region.div(monthly_total, axis=0) * 100

    regions = list(monthly_pct.columns)
    recent_periods = periods[-recent_months:] if len(periods) > recent_months else periods
    prior_periods = periods[: -recent_months] if len(periods) > recent_months else []

    recent_avg = monthly_pct.loc[recent_periods].mean() if recent_periods else pd.Series(0, index=regions)
    prior_avg = monthly_pct.loc[prior_periods].mean() if prior_periods else pd.Series(0, index=regions)
    delta_pp = recent_avg.reindex(regions, fill_value=0) - prior_avg.reindex(regions, fill_value=0)

    return {
        "periods": periods,
        "regions": regions,
        "monthly_pct": {
            region: [round(monthly_pct.loc[p, region], 1) for p in periods] for region in regions
        },
        "recent_months": recent_periods,
        "recent_avg_pct": {r: round(v, 1) for r, v in recent_avg.items()},
        "prior_avg_pct": {r: round(v, 1) for r, v in prior_avg.items()},
        "delta_pp": {r: round(v, 1) for r, v in delta_pp.items()},
    }


def _recent_prior_split(df: pd.DataFrame, recent_weeks: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    df = _with_kst(df)
    last_ts = df["datetime_kst"].max()
    recent_start = last_ts - pd.Timedelta(weeks=recent_weeks)
    prior_start = recent_start - pd.Timedelta(weeks=recent_weeks)

    recent_df = df[df["datetime_kst"] > recent_start]
    prior_df = df[(df["datetime_kst"] > prior_start) & (df["datetime_kst"] <= recent_start)]
    return recent_df, prior_df, prior_start, recent_start, last_ts


def compute_artist_delta_ranking(df: pd.DataFrame, recent_weeks: int = 4, top_n: int = 10) -> dict:
    """최근 N주 vs 그 이전 N주 재생 횟수 비교로 아티스트 급상승/급하락 랭킹을 계산한다."""
    recent_df, prior_df, prior_start, recent_start, last_ts = _recent_prior_split(df, recent_weeks)

    recent_counts = recent_df["artist"].value_counts()
    prior_counts = prior_df["artist"].value_counts()
    all_artists = set(recent_counts.index) | set(prior_counts.index)

    deltas = []
    for artist in all_artists:
        r = int(recent_counts.get(artist, 0))
        p = int(prior_counts.get(artist, 0))
        deltas.append({"name": artist, "recent": r, "prior": p, "delta": r - p})

    top_gainers = sorted(deltas, key=lambda x: x["delta"], reverse=True)[:top_n]
    top_decliners = sorted(deltas, key=lambda x: x["delta"])[:top_n]
    top_decliners = [d for d in top_decliners if d["delta"] < 0]

    return {
        "recent_weeks": recent_weeks,
        "recent_range": [recent_start.strftime("%Y-%m-%d"), last_ts.strftime("%Y-%m-%d")],
        "prior_range": [prior_start.strftime("%Y-%m-%d"), recent_start.strftime("%Y-%m-%d")],
        "top_gainers": top_gainers,
        "top_decliners": top_decliners,
    }


def compute_tag_delta_ranking(df: pd.DataFrame, recent_weeks: int = 4, top_n: int = 10) -> dict:
    """최근 N주 vs 그 이전 N주 태그 가중치 비교로 장르 급상승/급하락 랭킹을 계산한다."""
    recent_df, prior_df, prior_start, recent_start, last_ts = _recent_prior_split(df, recent_weeks)

    tag_cache: dict[str, list] = {}

    def tag_scores(period_df: pd.DataFrame) -> dict[str, float]:
        scores: dict[str, float] = {}
        artist_counts = period_df["artist"].value_counts()
        for artist_name, play_count in artist_counts.items():
            tags = load_artist_tags(artist_name, tag_cache)
            for tag in tags[:5]:
                tag_name = tag["name"].lower()
                weight = (tag["count"] / 100) * play_count
                scores[tag_name] = scores.get(tag_name, 0) + weight
        return scores

    recent_scores = tag_scores(recent_df)
    prior_scores = tag_scores(prior_df)
    all_tags = set(recent_scores) | set(prior_scores)

    deltas = []
    for tag in all_tags:
        r = round(recent_scores.get(tag, 0), 1)
        p = round(prior_scores.get(tag, 0), 1)
        deltas.append({"name": tag, "recent": r, "prior": p, "delta": round(r - p, 1)})

    top_gainers = sorted(deltas, key=lambda x: x["delta"], reverse=True)[:top_n]
    top_decliners = sorted(deltas, key=lambda x: x["delta"])[:top_n]
    top_decliners = [d for d in top_decliners if d["delta"] < 0]

    return {
        "recent_weeks": recent_weeks,
        "recent_range": [recent_start.strftime("%Y-%m-%d"), last_ts.strftime("%Y-%m-%d")],
        "prior_range": [prior_start.strftime("%Y-%m-%d"), recent_start.strftime("%Y-%m-%d")],
        "top_gainers": top_gainers,
        "top_decliners": top_decliners,
    }


def compute_artist_churn(
    df: pd.DataFrame,
    recent_weeks: int = 4,
    min_history_plays: int = 8,
    surge_multiple: float = 3.0,
    top_n: int = 10,
) -> dict:
    """
    이탈: 최근 구간 이전엔 꾸준히 들었지만 최근엔 거의 재생이 없는 아티스트.
    재발견: 과거 대비 최근 재생 빈도가 급증한(배수 기준) 아티스트.
    """
    df = _with_kst(df)
    last_ts = df["datetime_kst"].max()
    recent_start = last_ts - pd.Timedelta(weeks=recent_weeks)

    recent_df = df[df["datetime_kst"] > recent_start]
    history_df = df[df["datetime_kst"] <= recent_start]

    if len(history_df) == 0:
        return {"recent_weeks": recent_weeks, "churned": [], "rediscovered": []}

    history_span_weeks = max(
        (recent_start - history_df["datetime_kst"].min()).days / 7, 1.0
    )

    history_counts = history_df["artist"].value_counts()
    recent_counts = recent_df["artist"].value_counts()

    churned = []
    rediscovered = []
    for artist, hist_count in history_counts.items():
        hist_weekly_avg = hist_count / history_span_weeks
        recent_count = int(recent_counts.get(artist, 0))
        recent_weekly_avg = recent_count / recent_weeks

        if hist_count >= min_history_plays and recent_count == 0:
            churned.append(
                {
                    "name": artist,
                    "history_plays": int(hist_count),
                    "history_weekly_avg": round(hist_weekly_avg, 2),
                }
            )
        elif hist_count > 0:
            ratio = recent_weekly_avg / max(hist_weekly_avg, 0.01)
            if ratio >= surge_multiple and recent_count >= 3:
                rediscovered.append(
                    {
                        "name": artist,
                        "history_plays": int(hist_count),
                        "history_weekly_avg": round(hist_weekly_avg, 2),
                        "recent_plays": recent_count,
                        "surge_multiple": round(ratio, 1),
                    }
                )

    churned.sort(key=lambda x: x["history_weekly_avg"], reverse=True)
    rediscovered.sort(key=lambda x: x["surge_multiple"], reverse=True)

    return {
        "recent_weeks": recent_weeks,
        "churned": churned[:top_n],
        "rediscovered": rediscovered[:top_n],
    }


def compute_recent_concentration(df: pd.DataFrame, days: int = 30, top_n: int = 10) -> dict:
    """최근 N일 재생 중, 그 기간 내 비중이 가장 큰 아티스트/장르 (절대 순위가 아닌 최근 집중도 기준)."""
    df = _with_kst(df)
    last_ts = df["datetime_kst"].max()
    window_start = last_ts - pd.Timedelta(days=days)
    window_df = df[df["datetime_kst"] > window_start]
    total = len(window_df)

    if total == 0:
        return {"days": days, "window_total_plays": 0, "top_artists": [], "top_tags": []}

    artist_counts = window_df["artist"].value_counts().head(top_n)
    top_artists = [
        {"name": name, "plays": int(count), "share_pct": round(count / total * 100, 1)}
        for name, count in artist_counts.items()
    ]

    tag_cache: dict[str, list] = {}
    tag_scores: dict[str, float] = {}
    for artist_name, play_count in window_df["artist"].value_counts().items():
        tags = load_artist_tags(artist_name, tag_cache)
        for tag in tags[:5]:
            tag_name = tag["name"].lower()
            weight = (tag["count"] / 100) * play_count
            tag_scores[tag_name] = tag_scores.get(tag_name, 0) + weight

    tag_total = sum(tag_scores.values()) or 1
    top_tags_sorted = sorted(tag_scores.items(), key=lambda x: x[1], reverse=True)[:top_n]
    top_tags = [
        {"name": name, "score": round(score, 1), "share_pct": round(score / tag_total * 100, 1)}
        for name, score in top_tags_sorted
    ]

    return {
        "days": days,
        "window_range": [window_start.strftime("%Y-%m-%d"), last_ts.strftime("%Y-%m-%d")],
        "window_total_plays": total,
        "top_artists": top_artists,
        "top_tags": top_tags,
    }
