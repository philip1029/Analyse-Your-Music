# -*- coding: utf-8 -*-
"""
preprocess.py

last.fm 스크로블 CSV(uts,utc_time,artist,album,track,source)에서 애플 뮤직 연동이
만든 가짜/중복 기록을 걸러내는 전처리 파이프라인. detect_fake_scrobbles.py 의 판정
함수를 재사용하고, 판정 근거의 강도에 따라 처리를 나눈다.

핵심 원칙
---------
1. source 열(A=애플 로그 유래, L=last.fm 유래)은 절대 바꾸지 않는다. 판정과 제거는
   L 행에만 적용하고 A 행은 손대지 않는다.
2. 기본은 dry-run(파일을 쓰지 않음). --apply 를 줘야 실제로 쓴다. 쓰기 전에 항상
   백업을 만들고, 지운 행은 이유/근거와 함께 data/preprocess_removed.csv 에 남긴다.
3. 근거가 강한 것만 지운다. 나머지는 지우지 않고 "보류(pending)"로 보고만 한다.

규칙과 근거 강도
----------------
[log] 애플 재생 로그가 있는 구간 (로그 종료 시각 이전)
  - 같은 곡이 곡 길이(±2초)만큼 떨어져 반복된 구간(run)에서
      그 날 애플 로그의 실제 재생 수가 0     -> run 전체 제거      (log:no_play)
      0 < 재생 수 < run 길이                 -> 초과분 제거         (log:excess)
    2026-09 기준 이 규칙으로 지운 6천여 행은 PLAY_END 재집계에서도 되살릴 행이 0건.
[provisional] 애플 로그가 없는 구간 (로그 종료 이후 또는 로그를 못 받았을 때)
  - 길이 일치 2회 묶음이면서 첫 행과 둘째 행이 모두 "다른 곡이 같은 초(±3초)에
    시작한 행"과 겹치면 둘째 행 제거 (provisional:pair_both_clash).
    이전 구간(로그로 확정) 통계: 이런 묶음의 85%가 가짜, 첫 행이 실제 시작일 확률 98.6%.
    약 15%는 실제 청취일 수 있으므로 'provisional'로 표시하고, 애플 로그를 새로
    받으면 해당 행을 되살려(reinstate) 로그로 다시 판정한다.
  - 그 밖의 2회 묶음 / 3회 이상 묶음 / 곡 길이 불명 / 같은 초 충돌은 제거하지 않는다.
[exact_dup] uts+artist+track 이 완전히 같은 L 행은 뒤의 것을 제거 (같은 초에 같은
  곡이 두 번 시작될 수 없다).

곡 길이 조회 순서: 애플 로그 Media Duration / 라이브러리 XML  ->  last.fm
track.getInfo(곡당 1회, 결과는 캐시). 비교 허용 오차는 모두 ±2초.

상태 파일 (data/preprocess_state.json)
--------------------------------------
  frozen_through_uts      이 시각 이하의 L 행은 확정(애플 로그 또는 이전 감사로 판정 끝)
  provisional_through_uts 이 시각 이하의 L 행에는 provisional 규칙을 이미 적용
  apple_log_end_uts       마지막으로 반영한 애플 로그의 종료 시각
처음 한 번 `--init-state` 로 만든다 (그 시점의 L 최신 uts 까지를 처리 완료로 본다).

사용법
------
    python3 scripts/preprocess.py --init-state            # 최초 1회
    python3 scripts/preprocess.py                         # dry-run: 새 행만 판정해서 보고
    python3 scripts/preprocess.py --apply                 # 실제 반영 (백업 + 제거 기록)
    python3 scripts/preprocess.py --apply --apple-dir "<Apple Music Activity 폴더>"
        # 애플 데이터를 새로 받았을 때: provisional 제거분을 되살려 로그로 재판정
환경변수 APPLE_ACTIVITY_DIR 이 있으면 --apple-dir 기본값으로 쓴다.
"""

import argparse
import bisect
import csv
import io
import json
import os
import shutil
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import detect_fake_scrobbles as det  # noqa: E402

ROOT = SCRIPT_DIR.parent
DEFAULT_DATA_DIR = ROOT / "data"

FROZEN_INIT_UTS = 1789516799      # 2026-09-15 23:59:59 UTC. 이전은 로그 기반 감사 완료분
CONTEXT_SECONDS = 7200            # run/충돌 판정에 쓰는 앞쪽 문맥 범위
CLASH_TOLERANCE = 3               # 다른 곡이 같은 초로 보는 허용 오차(초)
DURATION_TOLERANCE = det.DURATION_TOLERANCE_SECONDS
KEEP_BACKUPS = 5
LEDGER_FIELDS = ["uts", "utc_time", "artist", "album", "track", "source",
                 "rule", "confidence", "detail", "removed_at"]


# ---------------------------------------------------------------------------
# 입출력
# ---------------------------------------------------------------------------

def find_data_csv(data_dir):
    files = sorted(Path(data_dir).glob("*_scrobbles.csv"))
    return files[0] if files else None


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        header = list(reader.fieldnames or [])
        rows = [dict(r) for r in reader]
    return header, rows


def write_csv_atomic(path, header, rows, bom=True):
    """BOM + CRLF 형식을 유지해서 쓴다. 임시 파일에 쓴 뒤 교체한다."""
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=header, lineterminator="\r\n", extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    data = buf.getvalue().encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    tmp = Path(str(path) + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def load_json(path, default):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def utc_str(uts):
    return datetime.fromtimestamp(int(uts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def load_api_key():
    key = os.environ.get("LASTFM_API_KEY")
    if key:
        return key
    try:
        from dotenv import dotenv_values
        return dotenv_values(ROOT / ".env").get("LASTFM_API_KEY")
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 곡 길이 조회: 애플 로그/라이브러리 XML -> 캐시 -> last.fm API
# ---------------------------------------------------------------------------

class Durations:
    def __init__(self, cache_path, xml_map, log_map, api_key, use_api):
        self.cache_path = cache_path
        cache = load_json(cache_path, {})
        self.by_track = {k: set(v) for k, v in cache.get("by_track", {}).items()}
        self.lfm = dict(cache.get("lfm", {}))
        self.xml_map = xml_map or {}
        self.log_map = log_map or {}
        self.api_key = api_key
        self.use_api = use_api and bool(api_key)
        self.api_calls = 0
        self.dirty = False

    def _local(self, track):
        s = set(self.by_track.get(track, ()))
        s |= set(self.xml_map.get(track, ()))
        s |= set(self.log_map.get(track, {}).keys()) if self.log_map.get(track) else set()
        return s

    def _fetch_lfm(self, artist, track):
        q = urllib.parse.urlencode({"method": "track.getInfo", "artist": artist, "track": track,
                                    "autocorrect": 1, "api_key": self.api_key, "format": "json"})
        try:
            with urllib.request.urlopen("http://ws.audioscrobbler.com/2.0/?" + q, timeout=15) as r:
                d = json.load(r)
        except Exception:
            return None                      # 네트워크 오류는 캐시하지 않는다
        finally:
            time.sleep(0.22)
        self.api_calls += 1
        if "error" in d:
            return 0 if d.get("error") == 6 else None   # 6: 곡을 찾을 수 없음 -> 없음으로 캐시
        return round(int(d.get("track", {}).get("duration", 0) or 0) / 1000)

    def candidates(self, artist, track):
        """(길이 집합, 출처). 출처: local / lastfm / None."""
        local = self._local(track)
        if local:
            self.by_track[track] = set(self.by_track.get(track, ())) | local
            return local, "local"
        key = f"{artist}\t{track}"
        if key not in self.lfm and self.use_api:
            val = self._fetch_lfm(artist, track)
            if val is not None:
                self.lfm[key] = val
                self.dirty = True
        val = self.lfm.get(key, 0)
        return ({val}, "lastfm") if val and val > 0 else (set(), None)

    def save(self):
        save_json(self.cache_path, {"by_track": {k: sorted(v) for k, v in self.by_track.items()},
                                    "lfm": self.lfm})


def matches(gap, cands):
    return any(abs(gap - d) <= DURATION_TOLERANCE for d in cands)


# ---------------------------------------------------------------------------
# 판정
# ---------------------------------------------------------------------------

def judge(rows, state, log, durations_factory, args):
    """
    rows: 파일 전체 행(dict 리스트). 반환: (removals, pending, info)
      removals: {행 인덱스: {rule, confidence, detail}}
      pending : Counter + 예시 (지우지 않고 보고만 하는 것)
    """
    frozen, prov = state["frozen_through_uts"], state["provisional_through_uts"]
    log_end = log["end_uts"] if log else None
    lo = min(frozen, prov)
    L = sorted(((int(r["uts"]), i) for i, r in enumerate(rows)
                if r.get("source", "L") == "L" and str(r.get("uts", "")).isdigit()), key=lambda x: x[0])
    all_uts = [u for u, _ in L]
    all_trk = [rows[i]["track"] for _, i in L]

    def clash(track, sec):
        a = bisect.bisect_left(all_uts, sec - CLASH_TOLERANCE)
        b = bisect.bisect_right(all_uts, sec + CLASH_TOLERANCE)
        return any(t != track for t in all_trk[a:b])

    work = [{"row_id": i, "uts": u, "artist": rows[i]["artist"], "track": rows[i]["track"]}
            for u, i in L if u > lo - CONTEXT_SECONDS]
    runs = det.build_runs_by_track(work)
    removals, pending, examples = {}, Counter(), defaultdict(list)

    def note(kind, run):
        pending[kind] += 1
        if len(examples[kind]) < 5:
            examples[kind].append(f"{run['artist']} - {run['track']} @ {utc_str(run['start_uts'])}")

    def add(idx, rule, conf, detail, floor):
        if int(rows[idx]["uts"]) > floor and idx not in removals:
            removals[idx] = {"rule": rule, "confidence": conf, "detail": detail}

    # 완전 중복 (uts+artist+track)
    seen = {}
    for u, i in L:
        if u <= lo:
            continue
        k = (u, rows[i]["artist"], rows[i]["track"])
        if k in seen:
            add(i, "exact_dup", "certain", f"same key as row {seen[k]}", lo)
        else:
            seen[k] = i

    need = {r["track"] for r in runs}
    durations = durations_factory(need)
    for run in runs:
        n = run["count"]
        in_log_phase = log is not None and run["end_uts"] <= log_end
        floor = frozen if in_log_phase else prov
        if run["end_uts"] <= floor:
            continue                                   # 새로 판정할 행이 없음
        cands, src = durations.candidates(run["artist"], run["track"])
        if not cands:
            note("no_duration", run)
            continue
        if not matches(run["gap"], cands):
            continue                                   # 길이와 안 맞는 반복은 실제 청취로 본다
        ids = run["row_ids"]
        if in_log_phase:
            ac = det.apple_corroboration_count(run, log["counts"])
            if ac >= n:
                continue
            if ac == 0:
                targets, rule = ids, "log:no_play"
            else:
                targets, rule = ids[ac:], "log:excess"
            for rid in targets:
                add(rid, rule, "log-verified",
                    f"run={n};gap={run['gap']}s;apple_plays={ac};len_src={src}", floor)
        else:
            if n == 2 and clash(run["track"], run["utses"][0]) and clash(run["track"], run["utses"][1]):
                add(ids[1], "provisional:pair_both_clash", "provisional",
                    f"gap={run['gap']}s;len_src={src};first_uts={run['utses'][0]}", floor)
            else:
                note("pair_other" if n == 2 else "run_3plus", run)

    # 서로 다른 곡이 같은 초에 찍힌 경우: 지우지 않고 개수만 보고
    by_sec = defaultdict(set)
    for u, i in L:
        if u > prov:
            by_sec[u].add(rows[i]["track"])
    collisions = sum(1 for s in by_sec.values() if len(s) > 1)
    if collisions:
        pending["same_second_collision"] = collisions
    return removals, pending, examples


# ---------------------------------------------------------------------------
# 애플 로그
# ---------------------------------------------------------------------------

def load_log(apple_dir, library_xml, need_tracks):
    csv_path = Path(apple_dir) / "Apple Music Play Activity.csv"
    if not csv_path.exists():
        raise SystemExit(f"애플 재생 로그가 없습니다: {csv_path}")
    counts, durs, log_end = det.load_apple_activity(str(csv_path), need_tracks)
    xml = library_xml or (str(Path(apple_dir) / "전체.xml") if (Path(apple_dir) / "전체.xml").exists() else None)
    return {"counts": counts, "durations": durs, "end_uts": log_end}, det.load_library_durations(xml)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="last.fm 스크로블 전처리 (기본 dry-run)")
    ap.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    ap.add_argument("--apply", action="store_true", help="실제로 파일을 수정 (백업 + 제거 기록)")
    ap.add_argument("--init-state", action="store_true", help="상태 파일을 처음 만든다")
    ap.add_argument("--apple-dir", default=os.environ.get("APPLE_ACTIVITY_DIR"))
    ap.add_argument("--library-xml", default=None)
    ap.add_argument("--no-api", action="store_true", help="last.fm 곡 길이 조회를 쓰지 않는다")
    ap.add_argument("--rescan", action="store_true", help="provisional 구간 전체를 다시 훑는다")
    ap.add_argument("--json", action="store_true", help="요약을 JSON 한 줄로 출력")
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    csv_path = find_data_csv(data_dir)
    if not csv_path:
        raise SystemExit("data 폴더에 *_scrobbles.csv 가 없습니다.")
    state_path = data_dir / "preprocess_state.json"
    ledger_path = data_dir / "preprocess_removed.csv"
    cache_path = data_dir / "preprocess_durations.json"
    pending_path = data_dir / "preprocess_pending.csv"

    header, rows = read_csv(csv_path)
    if "source" not in header:
        raise SystemExit("source 열이 없는 파일입니다. (A/L 구분이 필요합니다)")
    max_L = max((int(r["uts"]) for r in rows if r["source"] == "L" and r["uts"].isdigit()), default=0)

    if args.init_state:
        if state_path.exists():
            raise SystemExit(f"이미 상태 파일이 있습니다: {state_path}")
        save_json(state_path, {"frozen_through_uts": FROZEN_INIT_UTS, "provisional_through_uts": max_L,
                               "apple_log_end_uts": None})
        print(f"상태 파일 생성: frozen<= {FROZEN_INIT_UTS} ({utc_str(FROZEN_INIT_UTS)} UTC), "
              f"provisional<= {max_L} ({utc_str(max_L)} UTC)")
        return
    state = load_json(state_path, None)
    if not state:
        raise SystemExit("상태 파일이 없습니다. 먼저 `--init-state` 를 한 번 실행하세요.")
    if args.rescan:
        state = dict(state, provisional_through_uts=state["frozen_through_uts"])

    # 새 애플 로그가 오면: provisional 로 지운 행 중 로그 구간에 들어오는 것을 되살려 재판정
    ledger = []
    if ledger_path.exists():
        with open(ledger_path, newline="", encoding="utf-8-sig") as f:
            ledger = list(csv.DictReader(f))
    log, xml_map, reinstated = None, {}, []
    if args.library_xml and not args.apple_dir:
        xml_map = det.load_library_durations(args.library_xml)
    if args.apple_dir:
        first_pass = {r["track"] for r in rows if r["source"] == "L"}      # 로그에서 모을 곡 범위
        log, xml_map = load_log(args.apple_dir, args.library_xml, first_pass)
        if log["end_uts"] and (state.get("apple_log_end_uts") or 0) >= log["end_uts"]:
            log, xml_map = None, {}                                         # 새 로그가 아님
    if log:
        keep = []
        for r in ledger:
            if r["rule"].startswith("provisional:") and int(r["uts"]) <= log["end_uts"]:
                reinstated.append({h: r.get(h, "") for h in header})
                reinstated[-1]["source"] = r.get("source", "L")
            else:
                keep.append(r)
        ledger = keep
        rows = rows + reinstated
        state = dict(state, frozen_through_uts=state["frozen_through_uts"])

    durations_holder = {}

    def factory(need):
        durations_holder["d"] = Durations(cache_path, xml_map, log["durations"] if log else None,
                                          load_api_key(), not args.no_api)
        return durations_holder["d"]

    removals, pending, examples = judge(rows, state, log, factory, args)

    # 요약
    by_rule = Counter(v["rule"] for v in removals.values())
    summary = {
        "mode": "apply" if args.apply else "dry-run",
        "rows_before": len(rows) - len(reinstated), "reinstated": len(reinstated),
        "removed": len(removals), "by_rule": dict(by_rule), "pending": dict(pending),
        "lastfm_api_calls": durations_holder["d"].api_calls if "d" in durations_holder else 0,
        "apple_log_used": bool(log),
    }
    summary["rows_after"] = len(rows) - len(removals)
    if args.json:
        print(json.dumps(summary, ensure_ascii=False))
    else:
        print(f"[{summary['mode']}] 파일: {csv_path.name}")
        print(f"  처리 구간: frozen<= {utc_str(state['frozen_through_uts'])} UTC, "
              f"provisional<= {utc_str(state['provisional_through_uts'])} UTC"
              + (f", 애플 로그 종료 {utc_str(log['end_uts'])} UTC" if log else ", 애플 로그 없음(provisional 규칙만)"))
        if reinstated:
            print(f"  되살려 재판정한 provisional 행: {len(reinstated)}")
        print(f"  제거 대상: {len(removals)}행 {dict(by_rule)}")
        for k, v in pending.items():
            ex = f"  예: {examples[k][0]}" if examples.get(k) else ""
            print(f"  보류(지우지 않음) {k}: {v}{ex}")
        print(f"  last.fm 곡 길이 API 호출: {summary['lastfm_api_calls']}회")

    if not args.apply:
        if not args.json:
            print("  (dry-run: 파일은 수정하지 않았습니다. 반영하려면 --apply)")
        return

    # --- 반영 ---
    if not removals and not reinstated:
        # 파일은 그대로 두고, 새로 훑은 구간만 처리 완료로 표시한다.
        new_state = dict(state)
        new_state["provisional_through_uts"] = max(max_L, load_json(state_path, {})["provisional_through_uts"])
        if log:
            new_state["frozen_through_uts"] = max(state["frozen_through_uts"], log["end_uts"])
            new_state["apple_log_end_uts"] = log["end_uts"]
        save_json(state_path, new_state)
        if "d" in durations_holder and durations_holder["d"].dirty:
            durations_holder["d"].save()
        if not args.json:
            print("  변경 없음: 파일을 수정하지 않았습니다.")
        return

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = csv_path.with_name(csv_path.name + f".bak_preprocess_{stamp}")
    shutil.copy2(csv_path, backup)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_ledger = list(ledger)
    for idx, v in sorted(removals.items(), key=lambda kv: -int(rows[kv[0]]["uts"])):
        r = rows[idx]
        new_ledger.append({"uts": r["uts"], "utc_time": r.get("utc_time", ""), "artist": r["artist"],
                           "album": r.get("album", ""), "track": r["track"], "source": r["source"],
                           "rule": v["rule"], "confidence": v["confidence"], "detail": v["detail"],
                           "removed_at": now})
    kept = [r for i, r in enumerate(rows) if i not in removals]
    kept.sort(key=lambda r: -int(r["uts"]))          # 안정 정렬: 최신순 유지
    write_csv_atomic(csv_path, header, kept)
    write_csv_atomic(ledger_path, LEDGER_FIELDS, new_ledger)

    max_now = max((int(r["uts"]) for r in kept if r["source"] == "L"), default=state["provisional_through_uts"])
    new_state = dict(state)
    new_state["provisional_through_uts"] = max(max_now, state["provisional_through_uts"])
    if log:
        new_state["frozen_through_uts"] = max(state["frozen_through_uts"], log["end_uts"])
        new_state["apple_log_end_uts"] = log["end_uts"]
    if args.rescan:                                   # rescan 은 워터마크를 되돌리지 않는다
        new_state["provisional_through_uts"] = max(max_now, load_json(state_path, {})["provisional_through_uts"])
    save_json(state_path, new_state)
    if "d" in durations_holder:
        durations_holder["d"].save()

    old = sorted(csv_path.parent.glob(csv_path.name + ".bak_preprocess_*"))
    for p in old[:-KEEP_BACKUPS]:
        p.unlink()
    if not args.json:
        print(f"  반영 완료: {len(kept)}행 (백업: {backup.name}, 제거 기록: {ledger_path.name})")


if __name__ == "__main__":
    main()
