# -*- coding: utf-8 -*-
"""
fill_apple_gaps.py

Last.fm 이 놓쳤지만 애플 재생 로그(Apple Music Play Activity.csv)에는 남아 있는 재생을, 스크로블 CSV 에 A 소스 행으로 채운다.
Last.fm 이 기준이고 애플은 보조 근거이므로, 이미 Last.fm(또는 기존 A) 기록이 있는 재생은 건드리지 않고 "기록이 비어 있는 곳"만 채운다.

후보 재생 (build_apple_sessions.py 와 같은 규칙으로 만든 세션)
  - PLAY_END 조각을 이어 붙인 세션의 재생 시간이 곡 길이의 50% 이상이거나 240초 이상 (Last.fm 의 스크로블 조건)

후보에서 뺄 때 (규칙 순서대로, 이유별 개수를 보고한다)
  1. out_of_range    : --since / --until 밖 (기본 시작은 Last.fm 첫 기록 날짜, 그 전은 가짜 반복 구간이 많아 제외)
  2. no_artist       : 아티스트를 못 찾음 (CSV 의 같은 곡·앨범 -> 애플 라이브러리 순으로 찾는다. 모르면 추측하지 않는다)
  3. covered_track   : 같은 곡이 시작 시각 -10분 ~ +15분 안에 이미 기록돼 있음 (L/A 무관)
  4. covered_album   : 같은 앨범의 다른 곡이 그 안에 기록돼 있음 (곡 이름 표기만 다르게 기록된 경우를 거른다)
  5. previously_removed : 전처리가 가짜로 지운 기록(preprocess_removed.csv)과 같은 곡·시각
  6. overlap         : 재생하는 동안 다른 곡이 기록돼 있음 (다른 기기·동시 재생 등으로 겹친 경우는 채우지 않는다)
  7. duplicate_session : 같은 곡이 같은 시각에 앨범 표기만 다른 세션으로 두 번 잡힘 (애플 로그가 한 재생을 두 번 적은 경우)

기본은 dry-run (data/apple_gap_candidates.csv 에 후보 목록만 쓴다). --apply 를 주면 백업(.bak_applegap_*)을 만들고
후보를 source="A" 행으로 넣고 data/apple_gap_log.csv 에 행마다 남긴다.

사용법
------
    python3 scripts/fill_apple_gaps.py                                  # .env 의 Apple 폴더로 dry-run
    python3 scripts/fill_apple_gaps.py --since 2026-09-10               # 더 좁은 구간만
    python3 scripts/fill_apple_gaps.py --apple-dir "<Apple Music Activity 폴더>" --apply
"""

import argparse
import csv
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))
sys.path.insert(0, str(ROOT / "backend"))
import build_apple_sessions as bas  # noqa: E402
import preprocess as pp  # noqa: E402
from csv_backup import make_backup  # noqa: E402

from app.analysis.keys import name_key  # noqa: E402

BEFORE, AFTER = 600, 900          # 같은 곡/앨범이 이미 기록돼 있는지 보는 창 (시작 시각 기준 초)
OVERLAP_LEAD, OVERLAP_TAIL = 20, 10
LOG_FIELDS = ["uts", "utc_time", "artist", "album", "track", "rule", "added_at"]
CANDIDATE_FIELDS = ["uts", "kst_time", "artist", "album", "track", "play_s"]
REASONS = ["out_of_range", "no_artist", "covered_track", "covered_album", "previously_removed", "overlap", "duplicate_session"]


def load_env_value(name):
    value = os.environ.get(name)
    if value:
        return value
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip().strip("\"'")
    return None


def build_sessions_all(groups):
    """Play Activity 의 (곡, 앨범)별 조각 -> 조건(50%/240초)을 넘는 세션 [{"uts", "track", "album", "play_s", "media_s"}]."""
    out = []
    for (track, album), segs in groups.items():
        for sess in bas.build_sessions(segs):
            total_ms = sum(s["play_ms"] for s in sess)
            media_ms = max(s["media_ms"] for s in sess)
            if not bas.qualifies(total_ms, media_ms):
                continue
            out.append({"uts": int(sess[0]["st"].timestamp()), "track": track, "album": album, "play_s": total_ms / 1000, "media_s": media_ms / 1000})
    return sorted(out, key=lambda s: s["uts"])


class _Index:
    """키 -> 정렬된 uts 배열. 시각 창 안에 있는지 이진 탐색으로 확인한다."""

    def __init__(self, pairs):
        by = defaultdict(list)
        for key, u in pairs:
            by[key].append(u)
        self.by = {k: np.sort(np.array(v, dtype="int64")) for k, v in by.items()}

    def near(self, key, start, before, after) -> bool:
        a = self.by.get(key)
        if a is None:
            return False
        i = int(np.searchsorted(a, start - before))
        return i < len(a) and a[i] <= start + after


def make_resolver(rows, apple_lookup=None):
    """(곡, 앨범) -> (아티스트, 앨범). CSV 에 이미 있는 같은 곡·앨범의 표기(Last.fm 기준)를 먼저 쓰고, 없으면 애플 라이브러리로 찾는다."""
    by_pair, by_track = defaultdict(Counter), defaultdict(Counter)
    for r in rows:
        a, al, t = (r.get("artist") or "").strip(), (r.get("album") or "").strip(), (r.get("track") or "").strip()
        if a and t:
            by_pair[(name_key(t), name_key(al))][(a, al)] += 1
            by_track[name_key(t)][a] += 1

    def resolve(track, album):
        counts = by_pair.get((name_key(track), name_key(album)))
        if counts:
            (artist, alb), _ = counts.most_common(1)[0]
            return artist, alb
        if apple_lookup is not None:
            artist, alb = apple_lookup(track, album)
            if artist:
                return artist, alb
        artists = by_track.get(name_key(track))
        if artists and len(artists) == 1:                    # 곡명이 CSV 에서 한 아티스트에만 대응할 때만
            return next(iter(artists)), album
        return "", album

    return resolve


def find_gap_rows(sessions, rows, removed=(), resolve=None, since=0, until=None):
    """
    sessions: build_sessions_all() 결과, rows: CSV 행(dict), removed: preprocess_removed.csv 행(dict),
    resolve: (곡, 앨범) -> (아티스트, 앨범). 돌려주는 값: (채울 행 [dict], 이유별 개수 Counter).
    """
    resolve = resolve or make_resolver(rows)
    tracks = _Index((name_key(r["track"]), int(r["uts"])) for r in rows if r.get("track") and r.get("uts"))
    albums = _Index((name_key(r["album"]), int(r["uts"])) for r in rows if r.get("album") and r.get("uts"))
    gone = _Index((name_key(r["track"]), int(r["uts"])) for r in removed if r.get("track") and r.get("uts"))
    all_uts = np.sort(np.array([int(r["uts"]) for r in rows if r.get("uts")], dtype="int64"))

    skipped, found, seen = Counter(), [], set()
    for s in sessions:
        u = s["uts"]
        if u < since or (until is not None and u > until):
            skipped["out_of_range"] += 1
            continue
        artist, album = resolve(s["track"], s["album"])
        if not artist:
            skipped["no_artist"] += 1
            continue
        tk = name_key(s["track"])
        if tracks.near(tk, u, BEFORE, AFTER):
            skipped["covered_track"] += 1
        elif (name_key(album) or name_key(s["album"])) and (albums.near(name_key(album), u, BEFORE, AFTER) or albums.near(name_key(s["album"]), u, BEFORE, AFTER)):
            skipped["covered_album"] += 1
        elif gone.near(tk, u, BEFORE, AFTER):
            skipped["previously_removed"] += 1
        else:
            lo, hi = u - OVERLAP_LEAD, u + max(int(s["play_s"]) - OVERLAP_TAIL, 0)
            i = int(np.searchsorted(all_uts, lo))
            if i < len(all_uts) and all_uts[i] <= hi:
                skipped["overlap"] += 1
            elif (tk, u) in seen:
                skipped["duplicate_session"] += 1
            else:
                seen.add((tk, u))
                found.append({"uts": u, "artist": artist, "album": album, "track": s["track"], "play_s": round(s["play_s"])})
    return found, skipped


def _utc_minute(u):
    return datetime.fromtimestamp(u, timezone.utc).strftime("%Y-%m-%d %H:%M")


def _kst(u):
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(u, ZoneInfo("Asia/Seoul")).strftime("%Y-%m-%d %H:%M")


def main():
    ap = argparse.ArgumentParser(description="Last.fm 이 놓친 재생을 애플 로그로 채우기 (기본 dry-run)", formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--data-dir", default=str(pp.DEFAULT_DATA_DIR))
    ap.add_argument("--apple-dir", default=None, help="Apple Music Activity 폴더 (기본: .env 의 APPLE_ACTIVITY_DIR)")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD (KST). 기본: CSV 의 Last.fm(L) 첫 기록 날짜")
    ap.add_argument("--until", default=None, help="YYYY-MM-DD (KST). 기본: 제한 없음")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    apple_dir = args.apple_dir or load_env_value("APPLE_ACTIVITY_DIR")
    if not apple_dir or not (Path(apple_dir) / "Apple Music Play Activity.csv").exists():
        raise SystemExit("Apple Music Play Activity.csv 가 있는 폴더가 필요합니다 (--apple-dir 또는 .env 의 APPLE_ACTIVITY_DIR).")
    apple_dir = Path(apple_dir)
    csv_path = pp.find_data_csv(args.data_dir)
    if not csv_path:
        raise SystemExit("data 폴더에 *_scrobbles.csv 가 없습니다.")
    header, rows = pp.read_csv(csv_path)

    def day_uts(day, end=False):
        t = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() - 9 * 3600     # KST 자정
        return int(t) + (86399 if end else 0)

    l_uts = [int(r["uts"]) for r in rows if r.get("source") == "L" and r.get("uts")]
    since = day_uts(args.since) if args.since else (min(l_uts) if l_uts else 0)
    until = day_uts(args.until, end=True) if args.until else None

    lookup = bas.load_artist_lookup(
        apple_dir / "Apple Music - Container Details.csv",
        apple_dir / "Apple Music Library Tracks.json.zip",
        apple_dir / "플레이리스트.xml",
        apple_dir / "전체.xml",
    )
    groups, _stats = bas.load_play_end_segments(str(apple_dir / "Apple Music Play Activity.csv"))
    sessions = build_sessions_all(groups)
    removed = []
    removed_path = Path(args.data_dir) / "preprocess_removed.csv"
    if removed_path.exists():
        removed = pp.read_csv(removed_path)[1]

    found, skipped = find_gap_rows(sessions, rows, removed, make_resolver(rows, lookup), since, until)

    mode = "apply" if args.apply else "dry-run"
    print(f"[{mode}] {csv_path.name}: 애플 세션 {len(sessions):,}개 중 구간 {_kst(since)} ~ {_kst(until) if until else '로그 끝'}")
    print(f"  채울 재생: {len(found):,}회 (곡 {len({f['track'] for f in found})}개, 재생 {sum(f['play_s'] for f in found) / 3600:.1f}시간)")
    print("  뺀 이유: " + ", ".join(f"{r} {skipped.get(r, 0):,}" for r in REASONS))
    by_month = Counter(_kst(f["uts"])[:7] for f in found)
    print("  월별: " + ", ".join(f"{m} {n}" for m, n in sorted(by_month.items())))

    cand_path = Path(args.data_dir) / "apple_gap_candidates.csv"
    pp.write_csv_atomic(cand_path, CANDIDATE_FIELDS, [{**f, "kst_time": _kst(f["uts"])} for f in sorted(found, key=lambda f: f["uts"])])
    print(f"  후보 목록: {cand_path.name} (확인용)")
    if not args.apply:
        print("  (dry-run: 스크로블 CSV 는 수정하지 않았습니다. 반영하려면 --apply)")
        return
    if not found:
        print("  채울 재생이 없습니다.")
        return

    backup = make_backup(csv_path, "applegap")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    added = [{"uts": str(f["uts"]), "utc_time": _utc_minute(f["uts"]), "artist": f["artist"], "album": f["album"], "track": f["track"], "source": "A"} for f in found]
    merged = sorted(rows + added, key=lambda r: -int(r["uts"]))             # 최신순 유지 (같은 시각은 원래 순서 그대로)
    pp.write_csv_atomic(csv_path, header, merged)
    log_path = Path(args.data_dir) / "apple_gap_log.csv"
    old_log = []
    if log_path.exists():
        with open(log_path, newline="", encoding="utf-8-sig") as f:
            old_log = list(csv.DictReader(f))
    new_log = [{**{k: r[k] for k in ("uts", "utc_time", "artist", "album", "track")}, "rule": "apple_gap", "added_at": now} for r in added]
    pp.write_csv_atomic(log_path, LOG_FIELDS, old_log + new_log)
    print(f"  반영 완료: {len(added):,}행 추가 (백업: {backup.name}, 기록: {log_path.name})")


if __name__ == "__main__":
    main()
