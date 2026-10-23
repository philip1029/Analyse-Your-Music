# -*- coding: utf-8 -*-
"""
fill_album_years.py

내 라이브러리의 모든 앨범의 발매연도를 찾아 data/album_years.json 에 저장한다 (Music by decade 의 바탕).
조회 순서·규칙은 backend/app/album_years.py 의 설명을 볼 것 (수동 보정 config/album_years.txt -> MusicBrainz -> Apple 내보내기).

  - 많이 들은 앨범부터 처리하고, 중간에 멈춰도(Ctrl-C) 지금까지의 결과는 저장된다. 다시 실행하면 이어서 한다.
  - 이미 찾은 앨범은 다시 조회하지 않는다. 못 찾은 앨범은 30일 뒤에 다시 시도한다 (--retry-unknown 이면 바로).
  - MusicBrainz 는 초당 1회 제한이 있어서 앨범당 1~2초가 걸린다 (앨범 2천 개면 처음 한 번 약 1시간).
  - 일시적 오류(네트워크·503)는 저장하지 않는다.

사용법
------
    python3 scripts/fill_album_years.py --dry-run             # 네트워크 없이 규모만 확인
    python3 scripts/fill_album_years.py                       # 전체 (이어서 실행 가능)
    python3 scripts/fill_album_years.py --limit 25            # 일부만 (최신 스크롭 불러오기 버튼은 새 앨범만 소량씩 이 옵션으로 실행)
    python3 scripts/fill_album_years.py --json --limit 25     # 결과를 JSON 한 줄로
    python3 scripts/fill_album_years.py --apple-only          # MusicBrainz 를 쓰지 않고 Apple 내보내기만으로 채움
    python3 scripts/fill_album_years.py --apple-dir "<Apple Music Activity 폴더>"
환경변수: APPLE_ACTIVITY_DIR (--apple-dir 기본값, .env 도 읽음)
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import pandas as pd  # noqa: E402

from app import album_years as ay  # noqa: E402


def load_env_value(name):
    value = os.environ.get(name)
    if value:
        return value
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip('"\'')
    return None


def main():
    ap = argparse.ArgumentParser(description="앨범 발매연도 캐시 채우기 (이어서 실행 가능)")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    ap.add_argument("--apple-dir", default=None)
    ap.add_argument("--limit", type=int, default=0, help="이번에 조회할 최대 앨범 수 (0 = 전부)")
    ap.add_argument("--apple-only", action="store_true", help="MusicBrainz 를 쓰지 않음")
    ap.add_argument("--retry-unknown", action="store_true", help="못 찾은 앨범도 기간과 상관없이 다시 시도")
    ap.add_argument("--dry-run", action="store_true", help="네트워크 없이 규모만 보여 줌")
    ap.add_argument("--json", action="store_true", help="결과를 JSON 한 줄로만 출력")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    csv_files = sorted(data_dir.glob("*_scrobbles.csv"))
    if not csv_files:
        raise SystemExit("data 폴더에 *_scrobbles.csv 가 없습니다.")
    cache_path = data_dir / ay.CACHE_NAME
    cache = ay.load_cache(cache_path)
    overrides = ay.load_overrides()
    apple = ay.load_apple_years(args.apple_dir or load_env_value("APPLE_ACTIVITY_DIR"))

    pairs = ay.album_pairs(pd.read_csv(csv_files[0], encoding="utf-8-sig").fillna(""))
    now = time.time()
    retry_days = 0 if args.retry_unknown else ay.RETRY_UNKNOWN_DAYS
    todo = [p for p in pairs if ay.override_for(overrides, p[0], p[1]) is None and ay.needs_lookup(cache.get(ay.cache_key(p[0], p[1])), now, retry_days)]
    known = sum(1 for a, b, _ in pairs if ay.override_for(overrides, a, b) or (cache.get(ay.cache_key(a, b)) or {}).get("year"))
    say = (lambda *_a, **_k: None) if args.json else print
    say(f"앨범 {len(pairs)}개 · 연도 알고 있음 {known}개 (수동 보정 {len(overrides)}줄) · 이번에 조회할 앨범 {len(todo)}개 · Apple 내보내기 {'사용' if apple else '없음'} · MusicBrainz {'사용 안 함' if args.apple_only else '사용'}")
    if not todo:                                 # 할 일이 없으면 네트워크도 필요 없다
        if args.json:
            print(json.dumps({"found": 0, "unknown": 0, "skipped": 0, "remaining": 0}))
        return
    if args.dry_run:
        n = len(todo) if args.limit == 0 else min(len(todo), args.limit)
        say(f"(dry-run) MusicBrainz 호출 약 {n}~{2 * n}회, 예상 {n * 1.5 / 60:.0f}분 안팎. 실제로 하려면 --dry-run 없이 실행하세요.")
        return

    lock = data_dir / ay.LOCK_NAME
    if not ay.acquire_lock(lock):                # 다른 곳(백그라운드 조회·버튼)이 이미 채우는 중이면 겹치지 않게 바로 끝낸다
        say("이미 앨범 연도를 채우는 중이에요. 끝난 뒤에 다시 실행하세요.")
        if args.json:
            print(json.dumps({"found": 0, "unknown": 0, "skipped": 0, "remaining": len(todo), "busy": True}))
        return

    if args.apple_only:
        mb = None
    else:
        mb = ay.MusicBrainzClient()

    def progress(i, total, stats):
        ay.touch_lock(lock)
        ay.save_cache(cache_path, cache)
        say(f"  {i}/{total} — 찾음 {stats['found']}, 못 찾음 {stats['unknown']}, 오류로 보류 {stats['skipped']} (MusicBrainz 호출 {mb.calls if mb else 0})", flush=True)

    stats = {"found": 0, "unknown": 0, "skipped": 0, "remaining": len(todo), "stopped": False}
    try:
        # 잠그고 나서 다시 읽는다: 앞서 돌던 조회가 방금 끝났다면 그 결과 위에서 이어 간다
        cache = ay.load_cache(cache_path)
        stats = ay.fill_years(pairs, cache, mb, apple, overrides, limit=args.limit, now=now, progress=progress)
    except KeyboardInterrupt:
        say("\n중단합니다. 지금까지의 결과를 저장합니다.")
    finally:
        ay.save_cache(cache_path, cache)
        ay.release_lock(lock)
    if args.json:
        print(json.dumps(stats))
    else:
        print(f"완료: 찾음 {stats['found']}, 못 찾음 {stats['unknown']}, 오류로 보류 {stats['skipped']}, 남음 {stats['remaining']} · 저장: {cache_path.name}")
        if stats.get("stopped"):
            print("MusicBrainz 에 연달아 닿지 않아 멈췄어요. 잠시 뒤에 다시 실행하면 이어서 합니다.")


if __name__ == "__main__":
    main()
