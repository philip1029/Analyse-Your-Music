# -*- coding: utf-8 -*-
"""
fill_artist_tags.py

내 라이브러리의 모든 아티스트의 Last.fm 태그(장르)를 가져와 backend/cache/artists/ 에 저장한다.
Taste 탭의 "장르/태그 분포"는 이 캐시를 쓰므로, 태그를 못 가져온 아티스트는 분포에서 빠진다.

  - 재생 많은 아티스트부터 처리하고, 이미 캐시가 있으면 건너뛴다. 중간에 멈춰도(Ctrl-C) 이어서 실행할 수 있다.
  - 일시적 오류(네트워크·요청 한도)는 캐시하지 않고 다음에 다시 시도한다 ("태그 없음"과 구별).
  - "최신 스크롭 불러오기" 버튼도 새 아티스트에 대해 이 스크립트를 소량(--limit)으로 실행한다.

사용법
------
    python3 scripts/fill_artist_tags.py --dry-run          # 몇 명이 남았는지만 확인
    python3 scripts/fill_artist_tags.py                    # 전부 (아티스트당 약 0.4초)
    python3 scripts/fill_artist_tags.py --limit 40 --json  # 40명만, 결과를 JSON 한 줄로
환경변수: LASTFM_API_KEY (.env 도 읽음)
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402

from app.lastfm import client  # noqa: E402
from fill_durations import load_env_key  # noqa: E402


def is_cached(artist: str) -> bool:
    return (client.CACHE_DIR / f"{client._slugify(client.resolve_artist_name(artist))}.json").exists()


def pending_artists(df: pd.DataFrame) -> list[tuple[str, int]]:
    """태그 캐시가 아직 없는 아티스트 (재생 많은 순). 아티스트가 빈 행은 제외."""
    counts = df.loc[df["artist"].fillna("") != "", "artist"].value_counts()
    return [(name, int(n)) for name, n in counts.items() if not is_cached(name)]


def main():
    ap = argparse.ArgumentParser(description="아티스트 태그 캐시 채우기 (이어서 실행 가능)")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--limit", type=int, default=0, help="이번에 조회할 최대 아티스트 수 (0 = 전부)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true", help="결과를 JSON 한 줄로만 출력")
    args = ap.parse_args()

    csv_files = sorted(Path(args.data_dir).glob("*_scrobbles.csv"))
    if not csv_files:
        raise SystemExit("data 폴더에 *_scrobbles.csv 가 없습니다.")
    df = pd.read_csv(csv_files[0], encoding="utf-8-sig").fillna("")
    todo = pending_artists(df)
    say = (lambda *_a, **_k: None) if args.json else print
    say(f"태그 캐시가 없는 아티스트 {len(todo)}명" + (f" (이번에 {min(args.limit, len(todo))}명)" if args.limit else ""))
    if args.limit:
        todo = todo[: args.limit]
    if args.dry_run or not todo:
        if args.json:
            print(json.dumps({"fetched": 0, "failed": 0, "remaining": len(todo)}))
        return

    api_key = load_env_key()
    if not api_key:
        raise SystemExit("LASTFM_API_KEY 가 없습니다 (.env 또는 환경변수).")
    fetched = failed = 0
    try:
        for i, (name, _) in enumerate(todo, 1):
            client.get_artist_top_tags(name, api_key)
            if is_cached(name):                 # 일시적 오류면 캐시가 안 생긴다 -> 실패로 센다
                fetched += 1
            else:
                failed += 1
            if i % 50 == 0:
                say(f"  {i}/{len(todo)} — 저장 {fetched}, 일시적 실패 {failed}", flush=True)
    except KeyboardInterrupt:
        say("\n중단합니다. 지금까지 저장된 태그는 그대로 남아 있습니다.")
    remaining = len(pending_artists(df))
    if args.json:
        print(json.dumps({"fetched": fetched, "failed": failed, "remaining": remaining}))
    else:
        print(f"완료: 저장 {fetched}, 일시적 실패 {failed}, 남은 아티스트 {remaining}명")


if __name__ == "__main__":
    main()
