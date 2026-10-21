import json
import os
import subprocess
from pathlib import Path
import pandas as pd
from fastapi import FastAPI
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

from app.analysis.ai_prompt import build_ai_prompt
from app.analysis.ai_prompt_period import build_period_prompt, list_periods
from app.analysis.discovery import compute_discovery, get_discovery_timeline
from app.lastfm.client import invalidate_aliased_cache
from app.lastfm.album_art import get_album_art
from app.lastfm import cover_overrides
from app.analysis.cover_audit import audit_albums, check_unchecked
from app.lastfm.image_proxy import fetch_image
from app.analysis.report_card import build_report_card
from app.analysis.overview_cards import build_overview_cards
from app.lastfm.artist_art import get_artist_art
from app.analysis.validation import validate_csv
from app.analysis.filters import filter_by_date_range
from app.analysis.keys import unique_count, resolve_all
from app.analysis.library import ranked_page, artist_detail, album_detail, track_detail, durations
from app.analysis.listening_time import attach_durations, time_summary, weights
from app.analysis.consistency import compute_consistency, stats_for_keys
from app.analysis.taste import (
    get_artist_tags_page,
    fetch_next_artist_tags,
    compute_tag_distribution,
    compute_tag_evolution,
    compute_tag_evolution_dynamic,
)
from app.analysis.diversity import compute_diversity
from app.version_check import check_for_update, apply_update

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


@app.get("/api/update-check")
def update_check():
    return check_for_update()


@app.post("/api/update-apply")
def update_apply():
    return apply_update()


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


def _grouped(df: pd.DataFrame, by: str, metric: str) -> pd.Series:
    """by 열로 묶은 값: metric == "time" 이면 분(곡 길이 x 재생), 아니면 재생 횟수."""
    if metric == "time":
        return weights(df, "time").groupby(df[by]).sum().round(1)
    return df.groupby(by).size()


@app.get("/api/overview/cards")
def overview_cards(start: str | None = None, end: str | None = None):
    """Overview 통계 카드: 기간 값, 직전 같은 기간(전체 기간이면 최근 30일) 대비 증감, 미니 막대."""
    df = get_filtered_df(None, None)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}
    return build_overview_cards(df, start, end)


@app.get("/api/time/summary")
def time_summary_endpoint(start: str | None = None, end: str | None = None):
    """총 청취 시간(스크롭 횟수 x 곡 길이), 하루 평균, 가장 많이 들은 날."""
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}
    return time_summary(df)


@app.get("/api/listening/hourly")
def listening_hourly(metric: str = "plays", start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True, format="mixed")
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    df["hour"] = df["datetime_kst"].dt.hour

    hourly_counts = _grouped(df, "hour", metric).reindex(range(24), fill_value=0)

    return {
        "hours": list(range(24)),
        "counts": hourly_counts.tolist(),
        "metric": metric,
    }


@app.get("/api/listening/weekday")
def listening_weekday(metric: str = "plays", start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True, format="mixed")
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    df["weekday"] = df["datetime_kst"].dt.dayofweek

    weekday_counts = _grouped(df, "weekday", metric).reindex(range(7), fill_value=0)
    weekday_labels = ["월", "화", "수", "목", "금", "토", "일"]

    return {
        "weekdays": weekday_labels,
        "counts": weekday_counts.tolist(),
        "metric": metric,
    }


@app.get("/api/listening/monthly")
def listening_monthly(metric: str = "plays", start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True, format="mixed")
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    df["year_month"] = df["datetime_kst"].dt.strftime("%Y-%m")

    monthly_counts = _grouped(df, "year_month", metric).sort_index()

    return {
        "months": monthly_counts.index.tolist(),
        "counts": monthly_counts.values.tolist(),
        "metric": metric,
    }


@app.get("/api/listening/yearly")
def listening_yearly(metric: str = "plays", start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True, format="mixed")
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    df["year"] = df["datetime_kst"].dt.year

    yearly_counts = _grouped(df, "year", metric).sort_index()

    return {
        "years": yearly_counts.index.tolist(),
        "counts": yearly_counts.values.tolist(),
        "metric": metric,
    }


@app.get("/api/music/top")
def music_top(
    category: str = "artist",
    limit: int = 20,
    metric: str = "plays",
    start: str | None = None,
    end: str | None = None,
):
    """Top 목록. metric=plays 는 재생 횟수 순, metric=time 은 청취 시간(횟수 x 곡 길이) 순."""
    by_time = metric == "time"
    column_map = {"artist": "artist", "track": "track", "album": "album"}
    if category not in column_map:
        return {"error": f"category는 {list(column_map.keys())} 중 하나여야 합니다."}

    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    column = column_map[category]
    full = df                                   # 꾸준함 계산은 기간 전체 기준 (항목별 필터 전)
    df = df[df[column].notna() & (df[column] != "")]
    if by_time:
        df = attach_durations(df)

    results = []
    if column == "artist":
        counts_all = df["artist"].value_counts()
        if by_time:
            secs = df["dur_sec"].fillna(0).groupby(df["artist"]).sum().sort_values(ascending=False, kind="stable").head(limit)
            for name, sec in secs.items():
                results.append({"name": name, "count": int(counts_all[name]), "seconds": int(sec), "artist": None, "_key": name})
        else:
            for name, count in counts_all.head(limit).items():
                results.append({"name": name, "count": int(count), "artist": None, "_key": name})
    else:
        # 곡명·앨범명만 같은 다른 아티스트의 항목(Untitled, Eureka 등)은 따로, 같은 앨범의 크레딧 표기 차이는 합쳐서 센다
        keys, reps, names = resolve_all(df, column)
        df = df.assign(_key=keys, _rep=reps, _name=names)
        sizes = df.groupby("_key").size()
        if by_time:
            order = df["dur_sec"].fillna(0).groupby(df["_key"]).sum().sort_values(ascending=False, kind="stable").head(limit)
        else:
            order = sizes.sort_values(ascending=False, kind="stable").head(limit)
        for key in order.index:
            rows = df[df["_key"] == key]
            rep = rows["_rep"].iloc[0]
            item = {"name": rows["_name"].iloc[0], "count": int(sizes[key]), "artist": rep or None, "_key": key}
            if by_time:
                item["seconds"] = int(order[key])
            if column == "track":
                # 커버용: 이 곡이 가장 많이 기록된 앨범
                albums = rows["album"]
                albums = albums[albums.notna() & (albums != "")]
                item["album"] = albums.value_counts().index[0] if len(albums) else None
                item["duration"] = durations.get(item["artist"] or "", item["name"])
            results.append(item)

    # 날짜 편향도: 월별 재생 분포 (처음 들은 달 ~ 마지막 달)
    stats, months = stats_for_keys(full, category, [r["_key"] for r in results])
    for r in results:
        r["consistency"] = stats.get(r.pop("_key"))
    return {"category": category, "metric": metric, "months": months, "results": results}


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


TAG_FILL_LIMIT = 40   # 새로고침 한 번에 태그를 조회할 최대 아티스트 수
FILL_LIMIT = 60   # 새로고침 한 번에 길이를 조회할 최대 곡 수


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

    # 전처리 뒤에 곡/앨범 제목 표기를 Last.fm 표기로 통일한다 (Apple 기록의 대소문자 차이로 같은 곡이
    # 둘로 갈라지는 것을 막는다). 바꿀 행이 없으면 파일을 건드리지 않고, 바꾸면 백업과 기록을 남긴다.
    titles = None
    norm_script = script_path.with_name("normalize_titles.py")
    try:
        norm = subprocess.run(
            ["python3", str(norm_script), "--apply", "--json"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if norm.returncode == 0:
            json_lines = [ln for ln in norm.stdout.splitlines() if ln.startswith("{")]
            titles = json.loads(json_lines[-1]) if json_lines else None
        else:
            titles = {"error": (norm.stderr or norm.stdout)[-500:]}
    except subprocess.TimeoutExpired:
        titles = {"error": "제목 통일 실행 시간 초과"}
    except Exception as e:  # noqa: BLE001
        titles = {"error": str(e)}

    # 새로 생긴 곡의 길이를 채운다 (이미 아는 곡은 건너뛰고, 한 번에 FILL_LIMIT 곡까지만 해서 버튼이 오래 걸리지 않게
    # 한다. 남은 곡은 다음에 불러올 때 이어서 한다). 길이를 못 찾아도 새로고침은 성공이다.
    durations_result = None
    dur_script = script_path.with_name("fill_durations.py")
    try:
        dur_run = subprocess.run(
            ["python3", str(dur_script), "--json", "--limit", str(FILL_LIMIT)],
            capture_output=True,
            text=True,
            timeout=90,
        )
        if dur_run.returncode == 0:
            json_lines = [ln for ln in dur_run.stdout.splitlines() if ln.startswith("{")]
            durations_result = json.loads(json_lines[-1]) if json_lines else None
        else:
            durations_result = {"error": (dur_run.stderr or dur_run.stdout)[-300:]}
    except subprocess.TimeoutExpired:
        durations_result = {"error": "곡 길이 조회 시간 초과 (다음에 이어서 합니다)"}
    except Exception as e:  # noqa: BLE001
        durations_result = {"error": str(e)}

    # 새 아티스트의 태그(장르)도 소량 채운다 (Taste 탭 분포가 일부 아티스트만 덮는 것을 줄인다). 실패해도 새로고침은 성공이다.
    tags_result = None
    tag_script = script_path.with_name("fill_artist_tags.py")
    if os.environ.get("LASTFM_API_KEY"):
        try:
            tag_run = subprocess.run(
                ["python3", str(tag_script), "--json", "--limit", str(TAG_FILL_LIMIT)],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if tag_run.returncode == 0:
                json_lines = [ln for ln in tag_run.stdout.splitlines() if ln.startswith("{")]
                tags_result = json.loads(json_lines[-1]) if json_lines else None
            else:
                tags_result = {"error": (tag_run.stderr or tag_run.stdout)[-300:]}
        except subprocess.TimeoutExpired:
            tags_result = {"error": "태그 조회 시간 초과 (다음에 이어서 합니다)"}
        except Exception as e:  # noqa: BLE001
            tags_result = {"error": str(e)}

    return {"success": True, "output": result.stdout[-2000:], "preprocess": preprocess, "titles": titles, "durations": durations_result, "tags": tags_result}

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
def library_list(category: str = "artist", offset: int = 0, limit: int = 50, metric: str = "plays", start: str | None = None, end: str | None = None):
    """Last.fm 라이브러리 같은 순위 목록 (artist/album/track)."""
    if category not in ("artist", "album", "track"):
        return {"error": "category는 artist, album, track 중 하나여야 합니다."}
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}
    return ranked_page(df, category, max(0, offset), min(max(1, limit), 200), "time" if metric == "time" else "plays")


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
def library_track(name: str, artist: str = "", offset: int = 0, limit: int = 50, album: str = "", start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}
    return track_detail(df, artist or None, name, max(0, offset), min(max(1, limit), 200), album or None) or {"error": "해당 곡의 기록이 없습니다."}


@app.get("/api/album-art")
def album_art(artist: str = "", album: str = ""):
    """앨범 커버 주소를 반환한다. 사용자가 직접 올린 커버가 있으면 그것을, 없으면 Last.fm album.getInfo(디스크 캐시)를 쓴다."""
    manual = cover_overrides.get_url("album", artist, album)
    if manual:
        return {"url": manual, "cached": True, "source": "manual"}
    api_key = os.environ.get("LASTFM_API_KEY")
    if not api_key:
        return {"url": None, "error": "LASTFM_API_KEY가 설정되지 않았습니다."}
    return get_album_art(artist, album, api_key)


class CoverOverrideBody(BaseModel):
    kind: str                      # "album" 또는 "artist"
    artist: str = ""
    album: str = ""
    image: str                     # data:image/...;base64,... (브라우저가 줄여서 보낸다)


@app.post("/api/cover-override")
def cover_override_set(body: CoverOverrideBody):
    """커버/사진을 직접 지정한다. 자동 조회 결과보다 우선한다."""
    try:
        url = cover_overrides.set_override(body.kind, body.artist, body.album, body.image)
    except ValueError as e:
        return Response(content=str(e), status_code=400, media_type="text/plain")
    return {"url": url, "source": "manual"}


@app.delete("/api/cover-override")
def cover_override_clear(kind: str, artist: str = "", album: str = ""):
    """직접 지정한 커버를 지우고 자동 조회 결과로 되돌린다."""
    return {"removed": cover_overrides.clear_override(kind, artist, album)}


@app.get("/api/cover-file/{name}")
def cover_file(name: str):
    path = cover_overrides.file_path(name)
    if not path:
        return Response(content="없는 파일입니다.", status_code=404, media_type="text/plain")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=3600"})


@app.get("/api/cover-missing")
def cover_missing(top: int = 300):
    """많이 들은 앨범 상위 top 개 중 커버를 못 찾은 앨범 목록과 점검 현황."""
    df = get_filtered_df(None, None)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}
    return audit_albums(df, min(max(10, top), 1000))


@app.post("/api/cover-check")
def cover_check(limit: int = 30, top: int = 300):
    """아직 조회하지 않은 앨범(재생 많은 순)을 limit 개까지 Last.fm 에서 조회해 누락 여부를 확인한다."""
    api_key = os.environ.get("LASTFM_API_KEY")
    if not api_key:
        return {"error": "LASTFM_API_KEY가 설정되지 않았습니다."}
    df = get_filtered_df(None, None)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}
    return check_unchecked(df, api_key, min(max(1, limit), 100), min(max(10, top), 1000))


@app.get("/api/artist-art")
def artist_art(artist: str = ""):
    """아티스트 사진 주소를 반환한다. 사용자가 직접 올린 사진이 있으면 그것을, 없으면 Deezer 검색(디스크 캐시)을 쓴다."""
    manual = cover_overrides.get_url("artist", artist)
    if manual:
        return {"url": manual, "cached": True, "source": "manual"}
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
def listening_daily(metric: str = "plays", start: str | None = None, end: str | None = None):
    df = get_filtered_df(start, end)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}

    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True, format="mixed")
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    df["date"] = df["datetime_kst"].dt.strftime("%Y-%m-%d")

    daily_counts = _grouped(df, "date", metric)

    return {
        "metric": metric,
        "days": [
            {"date": date, "count": int(count) if metric != "time" else round(float(count), 1)}
            for date, count in daily_counts.items()
        ],
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


@app.get("/api/me")
def me():
    """공유 이미지 머리글 등에 쓰는 Last.fm 사용자 이름 (없으면 null)."""
    return {"username": os.environ.get("USERNAME")}


@app.get("/api/report-card")
def report_card(period: str = "month", anchor: str | None = None):
    """공유 이미지용 한 기간(week/month/year/all)의 요약·순위·시간대별 청취량. 날짜 필터는 적용하지 않는다."""
    df = get_filtered_df(None, None)
    if df is None:
        return {"error": "data 폴더에 csv 파일이 없습니다."}
    try:
        return build_report_card(df, period, anchor, os.environ.get("USERNAME"))
    except ValueError as e:
        return {"error": str(e)}


@app.get("/api/image-proxy")
def image_proxy(url: str):
    """커버 이미지를 canvas 에 그려 저장할 수 있게 CORS 가 열린 응답으로 중계한다 (허용된 이미지 호스트만)."""
    try:
        data, ctype = fetch_image(url)
    except ValueError as e:
        return Response(content=str(e), status_code=400, media_type="text/plain")
    except Exception:  # noqa: BLE001  (네트워크 오류 등)
        return Response(content="이미지를 가져오지 못했습니다.", status_code=502, media_type="text/plain")
    return Response(content=data, media_type=ctype, headers={"Cache-Control": "public, max-age=86400"})


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