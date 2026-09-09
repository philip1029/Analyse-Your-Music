import pandas as pd
from app.lastfm.client import get_artist_top_tags, resolve_artist_name
import json
from pathlib import Path


def get_artist_tags_page(
    df: pd.DataFrame,
    api_key: str,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """
    재생 횟수 순으로 정렬된 전체 아티스트 중,
    지정한 페이지 범위만큼만 태그를 조회해서 반환한다.
    (캐시에 없는 아티스트만 실제로 API 호출됨)
    """
    artist_counts = df["artist"].value_counts()  # 재생 많은 순으로 이미 정렬됨
    total_artists = len(artist_counts)

    start = (page - 1) * page_size
    end = start + page_size
    page_artists = artist_counts.iloc[start:end]

    results = []
    for artist_name, play_count in page_artists.items():
        tags = get_artist_top_tags(artist_name, api_key)
        results.append(
            {
                "artist": artist_name,
                "play_count": int(play_count),
                "tags": [t["name"] for t in tags[:5]],
            }
        )

    total_pages = (total_artists + page_size - 1) // page_size

    return {
        "page": page,
        "page_size": page_size,
        "total_artists": total_artists,
        "total_pages": total_pages,
        "artists": results,
    }


CACHE_DIR = Path(__file__).resolve().parent.parent.parent / "cache" / "artists"


def _slugify(artist_name: str) -> str:
    import re
    slug = artist_name.lower().strip()
    slug = re.sub(r"[^a-z0-9가-힣]+", "_", slug)
    return slug.strip("_") or "unknown"


def compute_tag_distribution(df: pd.DataFrame, top_n: int = 15) -> dict:
    """
    캐시에 이미 저장된 아티스트들의 태그를 모아서,
    재생 횟수로 가중치를 준 태그(장르) 분포를 계산한다.
    캐시에 없는 아티스트는 집계에서 제외된다 (아직 조회 안 된 아티스트).
    """
    artist_counts = df["artist"].value_counts()

    tag_scores: dict[str, float] = {}
    covered_artists = 0
    total_artists = len(artist_counts)

    for artist_name, play_count in artist_counts.items():
        resolved_name = resolve_artist_name(artist_name)
        cache_path = CACHE_DIR / f"{_slugify(resolved_name)}.json"
        if not cache_path.exists():
            continue  # 아직 태그를 안 가져온 아티스트는 건너뜀

        covered_artists += 1
        with open(cache_path, "r", encoding="utf-8") as f:
            tags = json.load(f)

        for tag in tags[:5]:  # 아티스트당 상위 5개 태그만 사용
            tag_name = tag["name"].lower()
            tag_weight = tag["count"] / 100  # Last.fm count는 0~100 스케일
            tag_scores[tag_name] = tag_scores.get(tag_name, 0) + tag_weight * play_count

    sorted_tags = sorted(tag_scores.items(), key=lambda x: x[1], reverse=True)

    return {
        "tags": [
            {"tag": name, "score": round(score, 1)}
            for name, score in sorted_tags[:top_n]
        ],
        "covered_artists": covered_artists,
        "total_artists": total_artists,
    }

def compute_tag_evolution(df: pd.DataFrame, top_n_tags: int = 6) -> dict:
    """
    월별로 나눠서 태그(장르) 가중치 변화를 계산한다.
    캐시에 있는 아티스트만 집계 대상 (아직 태그 조회 안 된 아티스트는 제외).
    """
    df = df.copy()
    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True)
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    df["year_month"] = df["datetime_kst"].dt.strftime("%Y-%m")

    periods = sorted(df["year_month"].unique())

    # 월별 x 태그별 가중치 저장
    period_tag_scores: dict[str, dict[str, float]] = {p: {} for p in periods}
    overall_tag_scores: dict[str, float] = {}

    tag_cache: dict[str, list] = {}

    for period in periods:
        period_df = df[df["year_month"] == period]
        artist_counts = period_df["artist"].value_counts()

        for artist_name, play_count in artist_counts.items():
            if artist_name not in tag_cache:
                cache_path = CACHE_DIR / f"{_slugify(artist_name)}.json"
                if not cache_path.exists():
                    tag_cache[artist_name] = []
                    continue
                with open(cache_path, "r", encoding="utf-8") as f:
                    tag_cache[artist_name] = json.load(f)

            tags = tag_cache[artist_name]
            for tag in tags[:5]:
                tag_name = tag["name"].lower()
                weight = (tag["count"] / 100) * play_count
                period_tag_scores[period][tag_name] = (
                    period_tag_scores[period].get(tag_name, 0) + weight
                )
                overall_tag_scores[tag_name] = overall_tag_scores.get(tag_name, 0) + weight

    # 전체 기간 기준 상위 N개 태그만 시리즈로 유지 (일관된 비교를 위해)
    top_tags = sorted(overall_tag_scores.items(), key=lambda x: x[1], reverse=True)[:top_n_tags]
    top_tag_names = [name for name, _ in top_tags]

    series = []
    for tag_name in top_tag_names:
        values = [round(period_tag_scores[p].get(tag_name, 0), 1) for p in periods]
        series.append({"tag": tag_name, "values": values})

    return {"periods": periods, "series": series}

def compute_tag_evolution_dynamic(df: pd.DataFrame, top_n_tags: int = 6) -> dict:
    """
    각 기간(월)마다 그 기간 안에서의 실제 Top N 태그를 계산한다.
    (고정된 태그 세트가 아니라, 기간별로 순위가 다를 수 있음)
    이 방식으로 뽑힌 태그들의 합집합을 시리즈로 만들고,
    특정 달에 해당 태그가 없으면 None으로 표시해 선이 끊기게 한다.
    """
    df = df.copy()
    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True)
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    df["year_month"] = df["datetime_kst"].dt.strftime("%Y-%m")

    periods = sorted(df["year_month"].unique())

    period_tag_scores: dict[str, dict[str, float]] = {p: {} for p in periods}
    tag_cache: dict[str, list] = {}
    period_top_tags: dict[str, set] = {}

    for period in periods:
        period_df = df[df["year_month"] == period]
        artist_counts = period_df["artist"].value_counts()

        for artist_name, play_count in artist_counts.items():
            if artist_name not in tag_cache:
                cache_path = CACHE_DIR / f"{_slugify(artist_name)}.json"
                if not cache_path.exists():
                    tag_cache[artist_name] = []
                    continue
                with open(cache_path, "r", encoding="utf-8") as f:
                    tag_cache[artist_name] = json.load(f)

            tags = tag_cache[artist_name]
            for tag in tags[:5]:
                tag_name = tag["name"].lower()
                weight = (tag["count"] / 100) * play_count
                period_tag_scores[period][tag_name] = (
                    period_tag_scores[period].get(tag_name, 0) + weight
                )

        # 이 기간 안에서 top N 태그
        sorted_tags = sorted(
            period_tag_scores[period].items(), key=lambda x: x[1], reverse=True
        )[:top_n_tags]
        period_top_tags[period] = {name for name, _ in sorted_tags}

    # 어느 한 달에서라도 top N에 든 적 있는 태그는 전부 시리즈에 포함 (합집합)
    all_relevant_tags: set = set()
    for tags in period_top_tags.values():
        all_relevant_tags |= tags

    series = []
    for tag_name in all_relevant_tags:
        values = []
        for period in periods:
            if tag_name in period_top_tags[period]:
                values.append(round(period_tag_scores[period].get(tag_name, 0), 1))
            else:
                values.append(None)  # 이 달엔 top N 밖 -> 선이 끊기도록 None
        series.append({"tag": tag_name, "values": values})

    return {"periods": periods, "series": series}