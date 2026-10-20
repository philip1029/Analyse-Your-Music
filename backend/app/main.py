import json
import os
import subprocess
from pathlib import Path
import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.analysis.ai_prompt import build_ai_prompt
from app.analysis.ai_prompt_period import build_period_prompt, list_periods
from app.analysis.discovery import compute_discovery, get_discovery_timeline
from app.lastfm.client import invalidate_aliased_cache
from app.lastfm.album_art import get_album_art
from app.lastfm.artist_art import get_artist_art
from app.analysis.validation import validate_csv
from app.analysis.filters import filter_by_date_range
from app.analysis.keys import unique_count, resolve_keys
from app.analysis.library import ranked_page, artist_detail, album_detail, track_detail
from app.analysis.consistency import compute_consistency, stats_for_keys
from app.analysis.taste import (
    get_artist_tags_page,
    fetch_next_artist_tags,
    compute_tag_distribution,
    compute_tag_evolution,
    compute_tag_evolution_dynamic,
)
from app.analysis.diversity import compute_diversity

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"


def load_csv_safely(path: Path) -> pd.DataFrame:
    """인코딩 문제(BOM 등)를 고려해서 CSV를 안전하게 읽는다."""
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="cp949")


def get_filtered_df(start: str | None, end: str | None) -> pd.DataFrame | None:
    """CSV를 읽고 기간 필터까지 적용한 데이터프레임을 반환한다."""
    csv_files = list(DATA_DIR.glob("*_scrobbles.csv"))
    if not csv_files:
        return None
    df = load_csv_safely(csv_files[0])
    # 애플 뮤직 유래(A) 기록 중 라이브러리에서 아티스트/앨범을 못 찾은 일부 곡은
    # artist/album/track이 빈 칸으로 저장되어 있는데, pandas가 이를 NaN(float)으로
    # 읽어들인다. 이 NaN이 그대로 내려가면 문자열 메서드 호출(.lower() 등)에서
    # AttributeError가 나거나 JSON 직렬화 시 "Out of range float values are not
    # JSON compliant: nan" 오류가 난다. 실제 분석/화면용 데이터는 여기서 한 번에
    # 빈 문자열로 정리해서, 이 함수를 쓰는 모든 엔드포인트가 안전하게 문자열로
    # 다룰 수 있게 한다. (원본 결측치 자체를 보고 싶은 /api/validate,
    # /api/debug/empty-album은 get_filtered_df를 쓰지 않고 load_csv_safely를
    # 직접 불러서 원본 NaN을 그대로 본다.)
    df[["artist", "album", "track"]] = df[["artist", "album", "track"]].fillna("")
    df = df.drop_duplicates(subset=["uts", "artist", "track"], keep="first")
    df = filter_by_date_range(df, start, end)
    return df


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/stats")
def stats(start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    if len(df) == 0:
        return {
            "total_scrobbles": 0,
            "unique_tracks": 0,
            "unique_artists": 0,
            "unique_albums": 0,
            "first_scrobble": None,
            "last_scrobble": None,
        }

    return {
        "total_scrobbles": len(df),
        "unique_tracks": unique_count(df, "track"),
        "unique_artists": df["artist"].nunique(),
        "unique_albums": unique_count(df, "album"),
        "first_scrobble": df["utc_time"].min(),
        "last_scrobble": df["utc_time"].max(),
    }


@app.get("/api/listening/hourly")
def listening_hourly(start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True, format="mixed")
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    df["hour"] = df["datetime_kst"].dt.hour

    hourly_counts = df.groupby("hour").size().reindex(range(24), fill_value=0)

    return {
        "hours": list(range(24)),
        "counts": hourly_counts.tolist(),
    }


@app.get("/api/listening/weekday")
def listening_weekday(start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True, format="mixed")
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    df["weekday"] = df["datetime_kst"].dt.dayofweek

    weekday_counts = df.groupby("weekday").size().reindex(range(7), fill_value=0)
    weekday_labels = ["월", "화", "수", "목", "금", "토", "일"]

    return {
        "weekdays": weekday_labels,
        "counts": weekday_counts.tolist(),
    }


@app.get("/api/listening/monthly")
def listening_monthly(start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True, format="mixed")
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    df["year_month"] = df["datetime_kst"].dt.strftime("%Y-%m")

    monthly_counts = df.groupby("year_month").size().sort_index()

    return {
        "months": monthly_counts.index.tolist(),
        "counts": monthly_counts.values.tolist(),
    }


@app.get("/api/listening/yearly")
def listening_yearly(start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True, format="mixed")
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    df["year"] = df["datetime_kst"].dt.year

    yearly_counts = df.groupby("year").size().sort_index()

    return {
        "years": yearly_counts.index.tolist(),
        "counts": yearly_counts.values.tolist(),
    }


@app.get("/api/music/top")
def music_top(
    category: str = "artist",
    limit: int = 20,
    start: str | None = None,
    end: str | None = None,
):
    column_map = {"artist": "artist", "track": "track", "album": "album"}
    if category not in column_map:
        return {"error": f"category는 {list(column_map.keys())} 중 하나여야 합니다."}

    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    column = column_map[category]
    full = df                                   # 꾸준함 계산은 기간 전체 기준 (항목별 필터 전)
    df = df[df[column].notna() & (df[column] != "")]

    results = []
    if column == "artist":
        for name, count in df["artist"].value_counts().head(limit).items():
            results.append({"name": name, "count": int(count), "artist": None, "_key": name})
    else:
        # 곡명·앨범명만 같은 다른 아티스트의 항목(Untitled, Eureka 등)은 따로, 같은 앨범의 크레딧 표기 차이는 합쳐서 센다
        keys, reps = resolve_keys(df, column)
        df = df.assign(_key=keys, _rep=reps)
        counts = df.groupby("_key").size().sort_values(ascending=False, kind="stable").head(limit)
        for key, count in counts.items():
            rows = df[df["_key"] == key]
            rep = rows["_rep"].iloc[0]
            item = {"name": rows[column].iloc[0], "count": int(count), "artist": rep or None, "_key": key}
            if column == "track":
                # 커버용: 이 곡이 가장 많이 기록된 앨범
                albums = rows["album"]
                albums = albums[albums.notna() & (albums != "")]
                item["album"] = albums.value_counts().index[0] if len(albums) else None
            results.append(item)

    # 날짜 편향도: 월별 재생 분포 (처음 들은 달 ~ 마지막 달)
    stats, months = stats_for_keys(full, category, [r["_key"] for r in results])
    for r in results:
        r["consistency"] = stats.get(r.pop("_key"))
    return {"category": category, "months": months, "results": results}


@app.get("/api/music/consistency")
def music_consistency(
    category: str = "track",
    min_plays: int = 20,
    min_months: int = 12,
    limit: int = 50,
    sort: str = "even",
    start: str | None = None,
    end: str | None = None,
):
    """꾸준히(고르게) 들은 항목 순위. sort=even 고른 순, sort=biased 한 시기에 몰린 순."""
    if category not in ("artist", "track", "album"):
        return {"error": "category는 artist, track, album 중 하나여야 합니다."}
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}
    return compute_consistency(df, category, min_plays=min_plays, min_months=min_months, limit=limit, sort=sort)


@app.get("/api/taste/artists")
def taste_artists(
    page: int = 1,
    page_size: int = 20,
    start: str | None = None,
    end: str | None = None,
):
    api_key = os.environ.get("LASTFM_API_KEY")
    if not api_key:
        return {"error": "LASTFM_API_KEY가 설정되지 않았습니다."}

    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    result = get_artist_tags_page(df, api_key, page=page, page_size=page_size)
    return result


@app.post("/api/taste/cache-fetch")
def taste_cache_fetch(
    count: int = 20,
    start: str | None = None,
    end: str | None = None,
):
    """
    아티스트별 태그 표를 보지 않고도, 재생 횟수 순으로 아직 캐시가 없는 아티스트의
    태그를 count명만큼 미리 가져와 캐시에 채워 넣는다.
    """
    api_key = os.environ.get("LASTFM_API_KEY")
    if not api_key:
        return {"error": "LASTFM_API_KEY가 설정되지 않았습니다."}

    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    result = fetch_next_artist_tags(df, api_key, count=count)
    return result


@app.get("/api/taste/tag-distribution")
def taste_tag_distribution(start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    result = compute_tag_distribution(df)
    return result


@app.get("/api/validate")
def validate():
    csv_files = list(DATA_DIR.glob("*_scrobbles.csv"))
    if not csv_files:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    df = load_csv_safely(csv_files[0])
    result = validate_csv(df)
    return result


@app.post("/api/refresh")
def refresh_scrobbles():
    username = os.environ.get("USERNAME")
    if not username:
        return {"success": False, "error": "USERNAME이 설정되지 않았습니다."}

    script_path = Path(__file__).resolve().parent.parent.parent / "scripts" / "callData.py"

    try:
        result = subprocess.run(
            ["python3", str(script_path), username],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "스크립트 실행 시간 초과"}

    if result.returncode != 0:
        return {"success": False, "error": result.stderr[-2000:]}

    # 새로 받은 기록에 전처리(가짜/중복 기록 제거)를 적용한다. 실패해도 새로고침 자체는
    # 성공으로 둔다 (원본은 백업되고, 지운 행은 data/preprocess_removed.csv 에 남는다).
    preprocess = None
    pre_script = script_path.with_name("preprocess.py")
    try:
        pre = subprocess.run(
            ["python3", str(pre_script), "--apply", "--json"],
            capture_output=True,
            text=True,
            timeout=180,
        )
        if pre.returncode == 0:
            json_lines = [ln for ln in pre.stdout.splitlines() if ln.startswith("{")]
            preprocess = json.loads(json_lines[-1]) if json_lines else None
        else:
            preprocess = {"error": (pre.stderr or pre.stdout)[-500:]}
    except subprocess.TimeoutExpired:
        preprocess = {"error": "전처리 실행 시간 초과"}
    except Exception as e:  # noqa: BLE001
        preprocess = {"error": str(e)}

    return {"success": True, "output": result.stdout[-2000:], "preprocess": preprocess}

@app.get("/api/taste/evolution")
def taste_evolution(
    start: str | None = None,
    end: str | None = None,
    mode: str = "fixed",
):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    if mode == "dynamic":
        result = compute_tag_evolution_dynamic(df)
    else:
        result = compute_tag_evolution(df)

    return result

@app.get("/api/diversity")
def diversity(start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    result = compute_diversity(df)
    return result

@app.get("/api/debug/empty-album")
def debug_empty_album():
    csv_files = list(DATA_DIR.glob("*_scrobbles.csv"))
    if not csv_files:
        return {"error": "no csv"}
    df = load_csv_safely(csv_files[0])
    empty_rows = df[df["album"].isna() | (df["album"] == "")]
    empty_rows = empty_rows.fillna("")  # NaN을 빈 문자열로 변환
    return empty_rows.to_dict(orient="records")

@app.post("/api/cache/invalidate-aliases")
def cache_invalidate_aliases():
    deleted = invalidate_aliased_cache()
    return {"deleted_files": deleted, "count": len(deleted)}

@app.get("/api/library/list")
def library_list(category: str = "artist", offset: int = 0, limit: int = 50, start: str | None = None, end: str | None = None):
    """Last.fm 라이브러리 같은 순위 목록 (artist/album/track)."""
    if category not in ("artist", "album", "track"):
        return {"error": "category는 artist, album, track 중 하나여야 합니다."}
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}
    return ranked_page(df, category, max(0, offset), min(max(1, limit), 200))


@app.get("/api/library/artist")
def library_artist(name: str, start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}
    return artist_detail(df, name) or {"error": "해당 아티스트의 기록이 없습니다."}


@app.get("/api/library/album")
def library_album(name: str, artist: str = "", start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}
    return album_detail(df, artist or None, name) or {"error": "해당 앨범의 기록이 없습니다."}


@app.get("/api/library/track")
def library_track(name: str, artist: str = "", offset: int = 0, limit: int = 50, start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}
    return track_detail(df, artist or None, name, max(0, offset), min(max(1, limit), 200)) or {"error": "해당 곡의 기록이 없습니다."}


@app.get("/api/album-art")
def album_art(artist: str = "", album: str = ""):
    """앨범 커버 주소를 반환한다 (Last.fm album.getInfo, 디스크 캐시). 없으면 url 이 null."""
    api_key = os.environ.get("LASTFM_API_KEY")
    if not api_key:
        return {"url": None, "error": "LASTFM_API_KEY가 설정되지 않았습니다."}
    return get_album_art(artist, album, api_key)


@app.get("/api/artist-art")
def artist_art(artist: str = ""):
    """아티스트 사진 주소를 반환한다 (Last.fm 은 사진을 주지 않아 Deezer 검색, 디스크 캐시). 없으면 url 이 null."""
    return get_artist_art(artist)


@app.get("/api/discovery/summary")
def discovery_summary(start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    result = compute_discovery(df)
    return result


@app.get("/api/discovery/timeline")
def discovery_timeline(
    category: str = "track",
    limit: int = 50,
    start: str | None = None,
    end: str | None = None,
):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    results = get_discovery_timeline(df, category=category, limit=limit)
    return {"category": category, "results": results}

@app.get("/api/listening/daily")
def listening_daily(start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True, format="mixed")
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    df["date"] = df["datetime_kst"].dt.strftime("%Y-%m-%d")

    daily_counts = df.groupby("date").size()

    return {
        "days": [
            {"date": date, "count": int(count)}
            for date, count in daily_counts.items()
        ]
    }


@app.get("/api/listening/day")
def listening_day(date: str, start: str | None = None, end: str | None = None):
    """히트맵에서 특정 날짜를 클릭했을 때, 그날의 청취 기록 전체를 시간순으로 반환한다."""
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True, format="mixed")
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    df["date"] = df["datetime_kst"].dt.strftime("%Y-%m-%d")

    day_df = df[df["date"] == date].sort_values("datetime_kst")
    # artist/album/track에 결측치(NaN)가 있으면 JSON으로 직렬화할 때
    # "Out of range float values are not JSON compliant: nan" 오류로 500이 남.
    # (애플 뮤직 유래 기록 중 아티스트를 못 찾은 몇몇 곡이 빈 값 -> NaN으로 읽힘)
    day_df = day_df.copy()
    day_df[["artist", "album", "track"]] = day_df[["artist", "album", "track"]].fillna("")

    tracks = [
        {
            "time": row["datetime_kst"].strftime("%H:%M"),
            "artist": row["artist"],
            "track": row["track"],
            "album": row["album"],
        }
        for _, row in day_df.iterrows()
    ]

    artist_counts = day_df["artist"].value_counts()

    return {
        "date": date,
        "total_plays": len(day_df),
        "unique_artists": int(day_df["artist"].nunique()) if len(day_df) else 0,
        "unique_tracks": unique_count(day_df, "track") if len(day_df) else 0,
        "top_artists": [{"name": name, "count": int(count)} for name, count in artist_counts.head(5).items()],
        "tracks": tracks,
    }


@app.get("/api/ai-prompt")
def ai_prompt(start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    prompt_text = build_ai_prompt(df)
    return {"prompt": prompt_text}


@app.get("/api/ai-prompt/periods")
def ai_prompt_periods(period: str = "month"):
    """월간/주간/연간 프롬프트에서 고를 수 있는 기간 목록 (최신순)."""
    if period not in ("month", "week", "year"):
        return {"error": "period 는 month, week, year 중 하나여야 합니다."}
    df = get_filtered_df(None, None)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}
    return {"periods": list_periods(df, period)}


@app.get("/api/ai-prompt/period")
def ai_prompt_period(period: str = "month", anchor: str | None = None):
    """한 달(YYYY-MM) / 한 주(그 주의 아무 날짜 YYYY-MM-DD) / 한 해(YYYY) 기준 분석 프롬프트.
    anchor 를 생략하면 기록이 있는 가장 최근 기간. 날짜 필터는 적용하지 않는다."""
    df = get_filtered_df(None, None)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}
    try:
        return build_period_prompt(df, period, anchor)
    except ValueError as e:
        return {"error": str(e)}