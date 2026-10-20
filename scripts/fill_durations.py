# -*- coding: utf-8 -*-
"""
fill_durations.py

내 라이브러리의 모든 곡(아티스트+곡명)의 길이를 찾아 data/track_durations.json 에 저장한다.
조회 순서·규칙은 backend/app/lastfm/durations.py 의 설명을 볼 것 (Apple 내보내기 -> Last.fm -> 꼬리표 제거 -> Last.fm 검색 -> Apple 곡명만).

  - 많이 들은 곡부터 처리하고, 중간에 멈춰도(Ctrl-C) 지금까지의 결과는 저장된다. 다시 실행하면 이어서 한다.
  - 이미 찾은 곡은 다시 조회하지 않는다. 못 찾은 곡은 30일 뒤에 다시 시도한다 (--retry-unknown 이면 바로).
  - 일시적 오류(네트워크·요청 한도)는 저장하지 않는다.

사용법
------
    python3 scripts/fill_durations.py --dry-run            # 네트워크 없이 규모만 확인
    python3 scripts/fill_durations.py                      # 전체 (약 30~40분, 이어서 실행 가능)
    python3 scripts/fill_durations.py --limit 200          # 일부만
    python3 scripts/fill_durations.py --apple-dir "<Apple Music Activity 폴더>"
환경변수: LASTFM_API_KEY (.env 도 읽음), APPLE_ACTIVITY_DIR (--apple-dir 기본값)
"""

import argparse
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import pandas as pd  # noqa: E402

from app.analysis.keys import resolve_all  # noqa: E402
from app.lastfm import durations as dur  # noqa: E402


def load_env_key():
    key = os.environ.get("LASTFM_API_KEY")
    if key:
        return key
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("LASTFM_API_KEY="):
                return line.split("=", 1)[1].strip().strip('"\'')
    return None


def track_pairs(csv_path):
    """앱이 곡을 세는 방식 그대로의 (대표 아티스트, 곡명, 재생 수), 재생 많은 순."""
    df = pd.read_csv(csv_path, encoding="utf-8-sig").fillna("")
    keys, reps, names = resolve_all(df, "track")
    valid = keys != ""
    work = pd.DataFrame({"artist": reps[valid], "track": names[valid], "key": keys[valid]})
    counts = work.groupby("key").agg(artist=("artist", "first"), track=("track", "first"), n=("key", "size"))
    return [(r.artist, r.track, int(r.n)) for r in counts.sort_values("n", ascending=False).itertuples()]


def main():
    ap = argparse.ArgumentParser(description="곡 길이 캐시 채우기 (이어서 실행 가능)")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--apple-dir", default=os.environ.get("APPLE_ACTIVITY_DIR"))
    ap.add_argument("--limit", type=int, default=0, help="이번에 조회할 최대 곡 수 (0 = 전부)")
    ap.add_argument("--no-search", action="store_true", help="Last.fm track.search 단계를 건너뜀")
    ap.add_argument("--retry-unknown", action="store_true", help="못 찾은 곡도 기간과 상관없이 다시 시도")
    ap.add_argument("--dry-run", action="store_true", help="네트워크 없이 규모만 보여 줌")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    csv_files = sorted(data_dir.glob("*_scrobbles.csv"))
    if not csv_files:
        raise SystemExit("data 폴더에 *_scrobbles.csv 가 없습니다.")
    cache_path = data_dir / dur.CACHE_NAME
    cache = dur.load_cache(cache_path)
    apple = dur.load_apple_durations(args.apple_dir)

    pairs = track_pairs(csv_files[0])
    now = time.time()
    retry_days = 0 if args.retry_unknown else dur.RETRY_UNKNOWN_DAYS
    todo = [(a, t, n) for a, t, n in pairs if dur.needs_lookup(cache.get(dur.cache_key(a, t)), now, retry_days)]
    known = sum(1 for a, t, _ in pairs if (cache.get(dur.cache_key(a, t)) or {}).get("sec"))
    print(f"곡 {len(pairs)}개 · 길이 알고 있음 {known}개 · 이번에 조회할 곡 {len(todo)}개 · Apple 내보내기 {'사용' if apple else '없음'}")
    if args.dry_run:
        offline = sum(1 for a, t, _ in todo if apple and apple.get_pair(a, t))
        print(f"(dry-run) 조회 대상 중 Apple 내보내기(아티스트+곡명 일치)만으로 채울 수 있는 곡 {offline}개. 나머지 {len(todo) - offline}개는 Last.fm 호출(곡당 1~3회).")
        return

    api_key = load_env_key()
    if not api_key:
        raise SystemExit("LASTFM_API_KEY 가 없습니다 (.env 또는 환경변수).")
    if args.limit:
        todo = todo[: args.limit]
    client = dur.LastFmClient(api_key)
    found = unknown = skipped = 0
    try:
        for i, (artist, track, n) in enumerate(todo, 1):
            res = dur.resolve_duration(artist, track, client, apple, use_search=not args.no_search)
            if res is None:
                skipped += 1                      # 일시적 오류: 저장하지 않고 다음에 다시
            else:
                cache[dur.cache_key(artist, track)] = {**res, "tried": int(time.time())}
                found, unknown = (found + 1, unknown) if res["sec"] else (found, unknown + 1)
            if i % 100 == 0:
                dur.save_cache(cache_path, cache)
                print(f"  {i}/{len(todo)} — 찾음 {found}, 못 찾음 {unknown}, 오류로 보류 {skipped} (Last.fm 호출 {client.calls})", flush=True)
    except KeyboardInterrupt:
        print("\n중단합니다. 지금까지의 결과를 저장합니다.")
    dur.save_cache(cache_path, cache)
    print(f"완료: 찾음 {found}, 못 찾음 {unknown}, 오류로 보류 {skipped} · 저장: {cache_path.name}")


if __name__ == "__main__":
    main()
