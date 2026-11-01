# -*- coding: utf-8 -*-
"""
dedupe_apple_twins.py

같은 재생이 A 행(애플 로그 유래)과 L 행(Last.fm 유래)으로 둘 다 들어 있는 경우(몇 초~2분 차이로 같은 곡이 두 번)를 찾아서
A 행을 지운다. Last.fm 이 기준이므로 L 행은 그대로 두고, 앱의 중복 제거(uts·아티스트·곡명이 모두 같을 때만 지움)에 걸리지 않아
같은 재생이 두 번 세어지는 것을 막는다.

규칙
----
  - 같은 곡(대소문자·띄어쓰기·기호 무시)이고 시각 차이가 --max-gap 초(기본 120) 이내인 A 행과 L 행을 짝지운다.
    아티스트는 같거나 서로 포함되거나 한쪽이 비어 있어야 한다.
  - 일대일로만 짝짓는다 (시간 차이가 가까운 쌍부터). A 행 둘과 L 행 하나가 있으면 A 행 하나만 지운다 —
    곡이 짧아 실제로 반복 재생한 경우를 지우지 않기 위해서다.
기본은 dry-run (data/apple_twin_candidates.csv 에 짝 목록만 쓴다). --apply 를 주면 백업(.bak_appletwin_*)을 만들고
A 행을 지우며 data/apple_twin_log.csv 에 지운 행과 짝지은 L 행을 남긴다.

사용법
------
    python3 scripts/dedupe_apple_twins.py                # dry-run
    python3 scripts/dedupe_apple_twins.py --max-gap 30   # 더 엄격하게
    python3 scripts/dedupe_apple_twins.py --apply
"""

import argparse
import csv
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(SCRIPT_DIR.parent / "backend"))
import preprocess as pp  # noqa: E402
from csv_backup import make_backup  # noqa: E402

from app.analysis.keys import name_key  # noqa: E402

DEFAULT_MAX_GAP = 120
CANDIDATE_FIELDS = ["a_uts", "l_uts", "diff_s", "kst_time", "artist", "track", "a_album", "l_album"]
LOG_FIELDS = ["a_uts", "l_uts", "diff_s", "artist", "a_album", "l_album", "track", "removed_at"]


def _artist_compatible(a, b) -> bool:
    ka, kb = name_key(a or ""), name_key(b or "")
    return not ka or not kb or ka == kb or ka in kb or kb in ka


def find_twins(rows, max_gap=DEFAULT_MAX_GAP):
    """[(A 행 인덱스, L 행 인덱스, 시간 차이(초))]: 같은 재생의 A/L 쌍을 가까운 순으로 일대일 짝짓는다."""
    a_by, l_by = defaultdict(list), defaultdict(list)
    for i, r in enumerate(rows):
        if not r.get("track") or not r.get("uts"):
            continue
        key = name_key(r["track"])
        if r.get("source") == "A":
            a_by[key].append(i)
        elif r.get("source") == "L":
            l_by[key].append(i)
    pairs = []
    for key, a_idx in a_by.items():
        for i in a_idx:
            for j in l_by.get(key, ()):
                diff = abs(int(rows[i]["uts"]) - int(rows[j]["uts"]))
                if diff <= max_gap and _artist_compatible(rows[i].get("artist"), rows[j].get("artist")):
                    pairs.append((diff, i, j))
    pairs.sort()
    used_a, used_l, out = set(), set(), []
    for diff, i, j in pairs:
        if i in used_a or j in used_l:
            continue
        used_a.add(i)
        used_l.add(j)
        out.append((i, j, diff))
    return sorted(out)


def _kst(u):
    return datetime.fromtimestamp(int(u), ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M:%S")


def main():
    ap = argparse.ArgumentParser(description="같은 재생의 A/L 쌍에서 A 행 지우기 (기본 dry-run)", formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=str(pp.DEFAULT_DATA_DIR))
    ap.add_argument("--max-gap", type=int, default=DEFAULT_MAX_GAP, help="같은 재생으로 볼 최대 시간 차이(초)")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    csv_path = pp.find_data_csv(args.data_dir)
    if not csv_path:
        raise SystemExit("data 폴더에 *_scrobbles.csv 가 없습니다.")
    header, rows = pp.read_csv(csv_path)
    twins = find_twins(rows, args.max_gap)

    print(f"[{'apply' if args.apply else 'dry-run'}] {csv_path.name}: A/L 쌍 {len(twins):,}개 (시간 차이 {args.max_gap}초 이내, 일대일)")
    buckets = Counter("0~10초" if d <= 10 else "11~60초" if d <= 60 else "61초 이상" for _, _, d in twins)
    print("  시간 차이: " + ", ".join(f"{k} {buckets.get(k, 0)}" for k in ("0~10초", "11~60초", "61초 이상")))
    by_month = Counter(_kst(rows[i]["uts"])[:7] for i, _, _ in twins)
    print("  월별: " + ", ".join(f"{m} {n}" for m, n in sorted(by_month.items())))
    for i, j, d in twins[:5]:
        print(f"  예) {rows[i]['artist']} - {rows[i]['track']} | A {_kst(rows[i]['uts'])[5:]} / L {_kst(rows[j]['uts'])[5:]} ({d}초)")

    cand_path = Path(args.data_dir) / "apple_twin_candidates.csv"
    pp.write_csv_atomic(cand_path, CANDIDATE_FIELDS, [
        {"a_uts": rows[i]["uts"], "l_uts": rows[j]["uts"], "diff_s": d, "kst_time": _kst(rows[i]["uts"]), "artist": rows[j]["artist"],
         "track": rows[j]["track"], "a_album": rows[i]["album"], "l_album": rows[j]["album"]} for i, j, d in twins])
    print(f"  짝 목록: {cand_path.name} (확인용)")
    if not args.apply:
        print("  (dry-run: 스크로블 CSV 는 수정하지 않았습니다. 반영하려면 --apply)")
        return
    if not twins:
        print("  지울 행이 없습니다.")
        return

    backup = make_backup(csv_path, "appletwin")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    drop = {i for i, _, _ in twins}
    pp.write_csv_atomic(csv_path, header, [r for k, r in enumerate(rows) if k not in drop])
    log_path = Path(args.data_dir) / "apple_twin_log.csv"
    old_log = []
    if log_path.exists():
        with open(log_path, newline="", encoding="utf-8-sig") as f:
            old_log = list(csv.DictReader(f))
    new_log = [{"a_uts": rows[i]["uts"], "l_uts": rows[j]["uts"], "diff_s": d, "artist": rows[i]["artist"], "a_album": rows[i]["album"],
                "l_album": rows[j]["album"], "track": rows[i]["track"], "removed_at": now} for i, j, d in twins]
    pp.write_csv_atomic(log_path, LOG_FIELDS, old_log + new_log)
    print(f"  반영 완료: A 행 {len(drop):,}개 삭제 (백업: {backup.name}, 기록: {log_path.name})")


if __name__ == "__main__":
    main()
