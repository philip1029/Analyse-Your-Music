import csv
import os
import sys
import time
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timezone
import requests
from tqdm import tqdm

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

API_KEY = os.environ.get("LASTFM_API_KEY")
BASE_URL = "http://ws.audioscrobbler.com/2.0/"

if not API_KEY:
    raise RuntimeError("LASTFM_API_KEY가 설정되지 않았습니다. .env 파일을 확인하세요.")

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
DATA_DIR.mkdir(exist_ok=True)

def get_last_uts_from_csv(filename):
    """기존 CSV 파일에서 가장 최근(큰) uts 값을 찾아 반환합니다."""
    if not os.path.exists(filename):
        return None

    max_uts = 0
    try:
        with open(filename, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("uts"):
                    try:
                        uts_val = int(row["uts"])
                        if uts_val > max_uts:
                            max_uts = uts_val
                    except ValueError:
                        continue
    except Exception as e:
        print(f"기존 파일 읽기 중 오류 발생: {e}")
        return None

    return max_uts if max_uts > 0 else None


def load_existing_csv(filename):
    """기존 CSV 데이터 전체를 읽어옵니다."""
    if not os.path.exists(filename):
        return []
    with open(filename, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        return list(reader)


def fetch_scrobbles_since(username, last_uts=None):
    """last_uts 이후의 신규 스크롭 데이터를 수집합니다."""
    page = 1
    total_pages = 1
    new_scrobbles = []

    # API 요청 파라미터 (from 설정 시 지정 타임스탬프 이후 데이터만 조회)
    params = {
        "method": "user.getrecenttracks",
        "user": username,
        "api_key": API_KEY,
        "format": "json",
        "limit": 200,
        "page": 1,
    }
    if last_uts:
        # 마지막 저장 uts보다 1초 뒤부터 조회
        params["from"] = last_uts + 1

    try:
        response = requests.get(BASE_URL, params=params, timeout=10)
        data = response.json()
        attr = data.get("recenttracks", {}).get("@attr", {})
        total_pages = int(attr.get("totalPages", 1))
        total_tracks = int(attr.get("total", 0))

        if total_tracks == 0:
            print("새로 추가된 스크롭 데이터가 없습니다.")
            return []
    except Exception as e:
        print(f"초기 페이지 정보 조회 실패: {e}")
        return []

    print(f"새로 가져올 데이터: 약 {total_tracks}개 ({total_pages} 페이지)")

    with tqdm(
        total=total_pages, desc="다운로드 진행률", unit="page"
    ) as pbar:
        while page <= total_pages:
            params["page"] = page
            try:
                response = requests.get(BASE_URL, params=params, timeout=10)
                if response.status_code != 200:
                    break

                data = response.json()
                if "error" in data:
                    break

                tracks = data.get("recenttracks", {}).get("track", [])
                if isinstance(tracks, dict):
                    tracks = [tracks]

                for track in tracks:
                    # 현재 재생 중인 곡 제외 (date/uts 없음)
                    if "@attr" in track and track["@attr"].get("nowplaying"):
                        continue

                    uts_str = track.get("date", {}).get("uts", "")
                    if not uts_str:
                        continue

                    uts_val = int(uts_str)

                    # ISO 형식의 UTC 시간 생성 (예: 2026-09-06 16:47:00 UTC)
                    utc_time_str = (
                        datetime.fromtimestamp(uts_val, tz=timezone.utc)
                        .strftime("%Y-%m-%d %H:%M:%S")
                    )

                    new_scrobbles.append(
                        {
                            "uts": uts_str,
                            "utc_time": utc_time_str,
                            "artist": track.get("artist", {}).get(
                                "#text", ""
                            ),
                            "album": track.get("album", {}).get("#text", ""),
                            "track": track.get("name", ""),
                            "source": "L",
                        }
                    )

                pbar.set_postfix({"신규 곡": len(new_scrobbles)})
                pbar.update(1)
                page += 1
                time.sleep(0.1)

            except Exception as e:
                print(f"\n오류 발생: {e}")
                break

    return new_scrobbles


def save_updated_csv(new_data, existing_data, filename):
    """신규 데이터와 기존 데이터를 합쳐 파일에 저장합니다."""
    # 지정한 컬럼 양식
    fieldnames = ["uts", "utc_time", "artist", "album", "track", "source"]

    # 신규 데이터 + 기존 데이터 병합
    combined_data = new_data + existing_data

    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(combined_data)

    print(
        f"\n업데이트 완료! 새로 추가된 곡: {len(new_data)}개 / 총 곡 수: {len(combined_data)}개"
    )


if __name__ == "__main__":
    if len(sys.argv) < 2:
        username = os.environ.get("USERNAME")
        if not username:
            print("사용법: python callData.py <username>")
            sys.exit(1)
    else:
        username = sys.argv[1]

    filename = str(DATA_DIR / f"{username}_scrobbles.csv")

    # 1. 기존 파일에서 마지막 uts 확인
    last_uts = get_last_uts_from_csv(filename)
    if last_uts:
        print(f"기존 파일 발견! 마지막 저장 timestamp(uts): {last_uts}")
    else:
        print("기존 파일이 없거나 데이터가 없습니다. 전체 데이터를 다운로드합니다.")

    # 2. 신규 데이터 가져오기
    new_data = fetch_scrobbles_since(username, last_uts)

    # 3. 기존 데이터와 병합하여 저장
    if new_data:
        existing_data = load_existing_csv(filename)
        save_updated_csv(new_data, existing_data, filename)
    else:
        print("최신 상태입니다. 저장할 변경 사항이 없습니다.")