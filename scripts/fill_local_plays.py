# -*- coding: utf-8 -*-
"""
fill_local_plays.py

음악 앱에 직접 가져온 로컬 파일(mp3 등)의 재생은 Last.fm 스크롭에도, Apple 재생 기록 내보내기(Play Activity)에도 남지 않는다.
라이브러리 내보내기(전체.xml)에는 곡마다 재생 횟수(Play Count)와 마지막 재생 시각(Play Date UTC)만 남아 있으므로, 그것으로 스크로블 CSV 를 채운다.

만드는 행 (모두 source="M")
  - 실제 행 : 마지막 재생 시각 그대로 1회 (estimated=0)
  - 추정 행 : 나머지 (재생 횟수 - 1)회를 마지막 재생 직전부터 곡 길이 + 30초 간격으로 거꾸로 이어 붙인다 (estimated=1).
              실제 시각을 모르므로 같은 날 연속 재생처럼 놓인다. 월별·시간대 통계에는 오차가 있고, 재생 횟수 합계는 보관함과 맞는다.

넣지 않는 곡 (이유별 개수를 보고한다)
  1. not_local        : 로컬 파일(Track Type = File)이 아니거나 재생 횟수·마지막 재생 시각이 없음 (카탈로그 곡은 Play Activity 가 맞다)
  2. already_recorded : 같은 곡이 (아티스트 또는 앨범까지 같게) 이미 스크로블에 있음 (보관함 횟수와 겹칠 수 있어 건드리지 않는다)
  3. before_range     : 마지막 재생이 CSV 의 첫 기록(--since) 보다 앞섬
추정 행은 보관함에 곡이 추가된 시각(Date Added) 과 --since 보다 앞으로는 놓지 않는다 (넘치는 횟수는 버리고 dropped 로 보고한다).

기본은 dry-run (data/local_plays_candidates.csv 에 후보만 쓴다). --apply 를 주면 백업(.bak_localplays_*)을 만들고 행을 넣고
data/local_plays_log.csv 에 행마다 남긴다. 되돌리려면 `python3 scripts/csv_backup.py restore <백업파일> --apply`.

사용법
------
    python3 scripts/fill_local_plays.py                         # data/apple/전체.xml 로 dry-run
    python3 scripts/fill_local_plays.py --exact-only            # 추정 없이 마지막 재생 1회씩만
    python3 scripts/fill_local_plays.py --apply
"""

import argparse
import csv
import plistlib
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT / "backend"))
import preprocess as pp  # noqa: E402
from csv_backup import make_backup  # noqa: E402

from app.analysis.keys import name_key  # noqa: E402

GAP_S = 30                 # 추정 재생 사이의 여유 (곡 길이에 더한다)
DEFAULT_DURATION_S = 240   # 길이를 모를 때
LOG_FIELDS = ["uts", "utc_time", "artist", "album", "track", "estimated", "rule", "added_at"]
CANDIDATE_FIELDS = ["uts", "kst_time", "artist", "album", "track", "estimated"]
REASONS = ["not_local", "already_recorded", "before_range"]


def _ts(value) -> int | None:
    """plist 의 날짜(UTC, tz 없음 또는 있음) -> epoch 초."""
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return int(value.timestamp())


def load_local_tracks(xml_path: Path) -> list[dict]:
    with open(xml_path, "rb") as f:
        tracks = plistlib.load(f).get("Tracks", {})
    return list(tracks.values())


def plan_local_plays(tracks, rows, since: int = 0, now: int | None = None, exact_only: bool = False):
    """
    라이브러리 곡 목록 + 현재 CSV 행 -> (채울 재생 [{"uts","artist","album","track","estimated"}], 뺀 이유별 개수, 버린 추정 횟수).
    """
    now = now if now is not None else int(datetime.now(timezone.utc).timestamp())
    by_artist = {(name_key(r.get("track", "")), name_key(r.get("artist", ""))) for r in rows if r.get("track")}
    by_album = {(name_key(r.get("track", "")), name_key(r.get("album", ""))) for r in rows if r.get("track") and r.get("album")}
    plan, skipped, dropped = [], Counter(), 0
    for t in tracks:
        name, artist, album = t.get("Name") or "", t.get("Artist") or "", t.get("Album") or ""
        count, last = int(t.get("Play Count") or 0), _ts(t.get("Play Date UTC"))
        if t.get("Track Type") != "File" or not name or count < 1 or last is None:
            skipped["not_local"] += 1
            continue
        if (name_key(name), name_key(artist)) in by_artist or (album and (name_key(name), name_key(album)) in by_album):
            skipped["already_recorded"] += 1
            continue
        if last < since or last > now:
            skipped["before_range"] += 1
            continue
        plan.append({"uts": last, "artist": artist, "album": album, "track": name, "estimated": 0})
        if exact_only:
            continue
        step = int((t.get("Total Time") or 0) / 1000 or DEFAULT_DURATION_S) + GAP_S
        floor = max(since, _ts(t.get("Date Added")) or 0)
        for k in range(1, count):
            u = last - k * step
            if u < floor:
                dropped += count - k
                break
            plan.append({"uts": u, "artist": artist, "album": album, "track": name, "estimated": 1})
    return plan, skipped, dropped


def _utc_minute(u):
    return datetime.fromtimestamp(u, timezone.utc).strftime("%Y-%m-%d %H:%M")


def _kst(u):
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(u, ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")


def main():
    ap = argparse.ArgumentParser(description="로컬 파일 재생을 보관함(전체.xml)으로 채우기 (기본 dry-run)", formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=str(pp.DEFAULT_DATA_DIR))
    ap.add_argument("--xml", default=None, help="라이브러리 내보내기 전체.xml (기본: <data-dir>/apple/전체.xml)")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD (KST). 기본: CSV 의 첫 기록")
    ap.add_argument("--exact-only", action="store_true", help="추정 없이 마지막 재생 1회씩만")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    xml_path = Path(args.xml) if args.xml else data_dir / "apple" / "전체.xml"
    if not xml_path.exists():
        raise SystemExit(f"{xml_path} 가 없습니다 (음악 앱: 파일 → 라이브러리 → 라이브러리 내보내기).")
    csv_path = pp.find_data_csv(str(data_dir))
    if not csv_path:
        raise SystemExit("data 폴더에 *_scrobbles.csv 가 없습니다.")
    header, rows = pp.read_csv(csv_path)
    if "source" not in header:
        raise SystemExit("source 열이 없는 파일입니다.")

    if args.since:
        since = int(datetime.strptime(args.since, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp()) - 9 * 3600
    else:
        since = min((int(r["uts"]) for r in rows if r.get("uts")), default=0)

    plan, skipped, dropped = plan_local_plays(load_local_tracks(xml_path), rows, since, exact_only=args.exact_only)
    exact = sum(1 for p in plan if not p["estimated"])
    mode = "apply" if args.apply else "dry-run"
    print(f"[{mode}] {csv_path.name}: 보관함 {xml_path.name}, 구간 {_kst(since)} ~")
    print(f"  채울 재생: {len(plan):,}회 (곡 {len({(p['artist'], p['track']) for p in plan})}개: 실제 시각 {exact:,}회 + 추정 {len(plan) - exact:,}회, 앞쪽 시간 부족으로 버린 추정 {dropped:,}회)")
    print("  뺀 곡: " + ", ".join(f"{r} {skipped.get(r, 0):,}" for r in REASONS))
    by_month = Counter(_kst(p["uts"])[:7] for p in plan)
    print("  월별: " + ", ".join(f"{m} {n}" for m, n in sorted(by_month.items())))

    cand_path = data_dir / "local_plays_candidates.csv"
    pp.write_csv_atomic(cand_path, CANDIDATE_FIELDS, [{**p, "kst_time": _kst(p["uts"])} for p in sorted(plan, key=lambda p: p["uts"])])
    print(f"  후보 목록: {cand_path.name} (확인용)")
    if not args.apply:
        print("  (dry-run: 스크로블 CSV 는 수정하지 않았습니다. 반영하려면 --apply)")
        return
    if not plan:
        print("  채울 재생이 없습니다.")
        return

    backup = make_backup(csv_path, "localplays")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    added = [{"uts": str(p["uts"]), "utc_time": _utc_minute(p["uts"]), "artist": p["artist"], "album": p["album"], "track": p["track"], "source": "M"} for p in plan]
    merged = sorted(rows + added, key=lambda r: -int(r["uts"]))             # 최신순 유지 (같은 시각은 원래 순서 그대로)
    pp.write_csv_atomic(csv_path, header, merged)
    log_path = data_dir / "local_plays_log.csv"
    old_log = []
    if log_path.exists():
        with open(log_path, newline="", encoding="utf-8-sig") as f:
            old_log = list(csv.DictReader(f))
    new_log = [{**{k: a[k] for k in ("uts", "utc_time", "artist", "album", "track")}, "estimated": p["estimated"], "rule": "local_plays", "added_at": now} for a, p in zip(added, plan)]
    pp.write_csv_atomic(log_path, LOG_FIELDS, old_log + new_log)
    print(f"  반영 완료: {len(added):,}행 추가 (백업: {backup.name}, 기록: {log_path.name})")


if __name__ == "__main__":
    main()
