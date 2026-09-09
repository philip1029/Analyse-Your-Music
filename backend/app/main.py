import os
import subprocess
from pathlib import Path
import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.analysis.discovery import compute_discovery, get_discovery_timeline
from app.lastfm.client import invalidate_aliased_cache
from app.analysis.validation import validate_csv
from app.analysis.filters import filter_by_date_range
from app.analysis.taste import (
    get_artist_tags_page,
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
        "unique_tracks": df["track"].nunique(),
        "unique_artists": df["artist"].nunique(),
        "unique_albums": df["album"].nunique(),
        "first_scrobble": df["utc_time"].min(),
        "last_scrobble": df["utc_time"].max(),
    }


@app.get("/api/listening/hourly")
def listening_hourly(start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True)
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

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True)
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

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True)
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

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True)
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
    df = df[df[column].notna() & (df[column] != "")]

    top_counts = df[column].value_counts().head(limit)

    results = []
    for name, count in top_counts.items():
        first_match = df[df[column] == name].iloc[0]
        results.append(
            {
                "name": name,
                "count": int(count),
                "artist": first_match["artist"] if column != "artist" else None,
            }
        )

    return {"category": category, "results": results}


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

    return {"success": True, "output": result.stdout[-2000:]}

@app.get("/api/taste/evolution")
def taste_evolution(start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    result = compute_tag_evolution(df)
    return result

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

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True)
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    df["date"] = df["datetime_kst"].dt.strftime("%Y-%m-%d")

    daily_counts = df.groupby("date").size()

    return {
        "days": [
            {"date": date, "count": int(count)}
            for date, count in daily_counts.items()
        ]
    }