# -*- coding: utf-8 -*-
"""
detect_fake_scrobbles.py

last.fm 스크로블 기록(uts,utc_time,artist,album,track,source 형식) 안에서
"애플 뮤직 라이브러리 기반 백필/중복 기록" 문제를 찾아내는 스크립트.

배경
----
iOS 공식 Last.fm 앱의 "Scan & submit scrobbles manually" 기능은 애플 뮤직이
저장하는 누적 재생 횟수/최근 재생 정보를 last.fm에 스크로블로 제출한다.
그런데 애플 뮤직은 개별 재생의 정확한 "시작~종료" 구간을 앱에 그대로
넘기지 않고, 재생횟수와 마지막 재생 시각 정도만 제공하기 때문에, 이 기능은
다음 두 가지 서로 다른 방식으로 왜곡된 기록을 만들어낸다.

  (A) 완전 백필(허구) : 라이브러리의 누적 재생 횟수(Play Count)만큼 같은 곡을
      last.fm에 복제 제출하면서, 실제로는 없는 타임스탬프를 "곡 길이만큼씩
      이어붙여서" 추정해 채운다. 이 경우 그 날 애플 실제 재생 로그에는
      대응하는 기록이 전혀 없거나 극히 적다.

  (B) 중복 기록(실제 재생이지만 2줄로 찍힘) : 실제로 들은 "단 한 번의 재생"이,
      "시작 시각"과 "계산된 종료 시각(시작+곡 길이)" 두 개의 서로 다른
      스크로블 항목으로 각각 제출된다. 앨범을 이어서 들으면 앞 곡의
      "종료로 계산된 시각"과 다음 곡의 "시작 시각"이 같은 초에 찍히면서,
      마치 "서로 다른 두 곡이 같은 순간에 재생된 것"처럼 보이게 된다.
      이 경우 애플 실제 로그를 보면 그 날 진짜 재생이 있었던 걸 확인할 수
      있지만, last.fm에는 그 진짜 재생 1회가 2줄로 부풀려져 있다.

공통된 지문은 같다 — 같은 곡이 연속으로 나타날 때 간격(초)이 그 곡 자체의
재생 시간과 정확히(오차 ±2초 이내) 일치한다는 것. 다만 애플 원본 로그와
대조했을 때 그 날 실제 재생 횟수가:
  - 0회면                              => (A) 완전 허구  -> REMOVE
  - 스크로블 개수보다 적지만 0은 아니면  => (B) 일부만 진짜, 나머지는 중복
                                            -> PARTIAL_DUPLICATE
                                            (스크로블 개수를 애플 실제 재생
                                             횟수만큼으로 줄여야 함)
  - 스크로블 개수 이상이면              => 전부 진짜               -> KEEP

사용법
------
    python detect_fake_scrobbles.py \
        --scrobbles /path/to/username_scrobbles.csv \
        --apple-activity "/path/to/Apple Music Play Activity.csv" \
        --library-xml "/path/to/전체.xml" \
        --row-output /path/to/classified_rows.csv \
        --report /path/to/report.md

--apply 를 추가하면 REMOVE/PARTIAL_DUPLICATE로 판정된 행을 실제로
원본 스크로블 CSV에서 제거한다 (원본은 자동으로 .bak 백업).
--apple-activity 와 --library-xml 은 둘 중 하나만 있어도 동작하지만,
정확도를 위해 가능하면 둘 다 넣는 것을 권장한다.

원칙: Last.fm 기록이 기준이고 애플 로그는 참고 자료다. "애플 로그에 없다"는 사실만으로
지우지 않는다. 애플 로그는 카탈로그 곡(스트리밍)만 기록하므로, 라이브러리 JSON 에서
카탈로그 식별자가 없는 곡(내 파일·구매·매칭 곡 등)은 로그 규칙(REMOVE/PARTIAL)에서 빼고
UNVERIFIABLE 로 두며 아무것도 지우지 않는다. (--no-catalog-check 로 끌 수 있음)
"""

import argparse
import csv
import json
import os
import plistlib
import re
import shutil
import unicodedata
import zipfile
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone

KST = timezone(timedelta(hours=9))

MAX_LOOP_GAP_SECONDS = 3600      # 이보다 긴 간격은 "반복 재생"으로 보지 않음
DURATION_TOLERANCE_SECONDS = 2   # 간격과 곡 길이를 비교할 때 허용 오차


# ---------------------------------------------------------------------------
# 1. 데이터 로딩
# ---------------------------------------------------------------------------

def load_scrobbles(path, source_filter=None):
    """last.fm 스크로블 CSV(uts,utc_time,artist,album,track[,source])를 읽어온다."""
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for idx, r in enumerate(reader):
            try:
                uts = int(r["uts"])
            except (KeyError, ValueError, TypeError):
                continue
            if source_filter and r.get("source", "L") != source_filter:
                continue
            rows.append({
                "row_id": idx,
                "uts": uts,
                "artist": r.get("artist", ""),
                "track": r.get("track", ""),
                "album": r.get("album", ""),
                "source": r.get("source", "L"),
                "_raw": r,
            })
    return rows


def load_library_durations(xml_path):
    if not xml_path or not os.path.exists(xml_path):
        return {}
    with open(xml_path, "rb") as f:
        lib = plistlib.load(f)
    name_to_durations = defaultdict(set)
    for _, t in lib.get("Tracks", {}).items():
        name = t.get("Name")
        total_ms = t.get("Total Time")
        if name and total_ms:
            name_to_durations[name].add(round(total_ms / 1000))
    return name_to_durations


def _key(s):
    """이름 비교용 정규화: NFKC, 소문자, 글자·숫자만 남김."""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(s)).lower())


class CatalogIndex:
    """
    애플 재생 로그는 Apple Music 카탈로그 곡(스트리밍)의 재생만 기록한다. 라이브러리에
    있지만 카탈로그 식별자(Apple Music Track Identifier)가 없는 곡(내 파일, 구매·매칭 곡
    등)은 아무리 들어도 로그에 안 남는다. 그런 곡에는 "애플 로그에 그날 재생이 없다"가
    가짜의 증거가 될 수 없으므로, 로그 기반 규칙(log:no_play / log:excess)에서 뺀다.

    판정: 아티스트+곡명 키로 먼저 찾고, 없으면 곡명만으로 찾는다(아티스트 표기 차이 보완,
    같은 곡명의 라이브러리 항목이 전부 카탈로그 없음일 때만). 라이브러리에 아예 없는 곡은
    스트리밍 곡으로 보고 False(= 기존 규칙 적용)를 돌려준다.
    """

    def __init__(self, tracks):
        self.by_artist_title, self.by_title = {}, {}
        for t in tracks:
            title, artist = t.get("Title"), t.get("Artist") or ""
            if not title:
                continue
            ident = str(t.get("Apple Music Track Identifier") or "").strip()
            has_catalog = bool(ident) and ident.lower() != "nan"
            ka, kt = f"{_key(artist)}|{_key(title)}", _key(title)
            self.by_artist_title[ka] = self.by_artist_title.get(ka, False) or has_catalog
            self.by_title[kt] = self.by_title.get(kt, False) or has_catalog

    def is_noncatalog(self, artist, track):
        ka = f"{_key(artist or '')}|{_key(track)}"
        if ka in self.by_artist_title:
            return not self.by_artist_title[ka]
        kt = _key(track)
        return kt in self.by_title and not self.by_title[kt]


def load_catalog_index(path):
    """Apple Music Library Tracks.json(.zip) -> CatalogIndex. 파일이 없으면 None."""
    if not path or not os.path.exists(path):
        return None
    if str(path).lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".json")), None)
            if name is None:
                return None
            tracks = json.loads(z.read(name))
    else:
        with open(path, encoding="utf-8") as f:
            tracks = json.load(f)
    return CatalogIndex(tracks)


def load_apple_activity(apple_csv_path, needed_tracks):
    """
    (곡명, KST 날짜) -> 실제 PLAY_START 이벤트 수,  곡명 -> 재생시간(초) 분포,
    애플 로그의 마지막 이벤트 시각(uts, 로그가 없으면 None)을 반환한다.
    """
    apple_counts = defaultdict(int)
    apple_durations = defaultdict(Counter)
    log_end_uts = None
    if not apple_csv_path or not os.path.exists(apple_csv_path):
        return apple_counts, apple_durations, log_end_uts

    with open(apple_csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 로그 종료 시각은 곡과 무관하게 모든 행에서 구한다. 이 시각 이후의
            # 스크로블은 "애플에 재생 기록이 없다"가 아니라 "애플 로그 자체가
            # 없다"는 뜻이라 apple_count == 0을 허구의 증거로 쓸 수 없다.
            for key in ("Event End Timestamp", "Event Start Timestamp"):
                ts_all = row.get(key)
                if ts_all:
                    try:
                        u = int(datetime.strptime(ts_all[:19], "%Y-%m-%dT%H:%M:%S")
                                .replace(tzinfo=timezone.utc).timestamp())
                    except ValueError:
                        continue
                    if log_end_uts is None or u > log_end_uts:
                        log_end_uts = u

            sn = row.get("Song Name") or ""
            if sn not in needed_tracks:
                continue

            md = row.get("Media Duration In Milliseconds")
            if md:
                try:
                    apple_durations[sn][round(float(md) / 1000)] += 1
                except ValueError:
                    pass

            if row.get("Event Type") != "PLAY_START":
                continue
            ts = row.get("Event Start Timestamp")
            if not ts:
                continue
            try:
                dt = datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
            except ValueError:
                continue
            date_str = dt.astimezone(KST).strftime("%Y-%m-%d")
            apple_counts[(sn, date_str)] += 1

    return apple_counts, apple_durations, log_end_uts


# ---------------------------------------------------------------------------
# 2. 완전 동일 간격 반복 구간(run) 탐지
# ---------------------------------------------------------------------------

def find_runs(sorted_items, max_gap=MAX_LOOP_GAP_SECONDS, min_plays=2):
    """
    sorted_items: [(uts, row_id), ...] (uts 오름차순)
    간격이 완전히 동일하게 연속되는 구간들을 찾는다.
    """
    runs = []
    gaps = [sorted_items[i + 1][0] - sorted_items[i][0] for i in range(len(sorted_items) - 1)]
    i, n = 0, len(gaps)
    while i < n:
        j = i
        while j + 1 < n and gaps[j + 1] == gaps[i] and gaps[i] < max_gap:
            j += 1
        run_len = j - i + 2
        if run_len >= min_plays and gaps[i] < max_gap:
            item_slice = sorted_items[i:j + 2]
            runs.append({
                "start_uts": item_slice[0][0],
                "end_uts": item_slice[-1][0],
                "count": run_len,
                "gap": gaps[i],
                "row_ids": [it[1] for it in item_slice],
                "utses": [it[0] for it in item_slice],
            })
        i = j + 1
    return runs


def build_runs_by_track(scrobble_rows):
    by_track = defaultdict(list)
    for r in scrobble_rows:
        by_track[(r["artist"], r["track"])].append((r["uts"], r["row_id"]))

    all_runs = []
    for (artist, track), items in by_track.items():
        items = sorted(items, key=lambda x: x[0])
        for run in find_runs(items):
            run["artist"] = artist
            run["track"] = track
            all_runs.append(run)
    return all_runs


# ---------------------------------------------------------------------------
# 3. 판정 (3단계: REMOVE / PARTIAL_DUPLICATE / KEEP / UNVERIFIABLE)
# ---------------------------------------------------------------------------

def duration_match(run, name_to_durations, apple_durations):
    candidates = set(name_to_durations.get(run["track"], set()))
    candidates |= set(apple_durations.get(run["track"], {}).keys())
    if not candidates:
        return None
    return any(abs(run["gap"] - d) <= DURATION_TOLERANCE_SECONDS for d in candidates)


def apple_corroboration_count(run, apple_counts):
    start_dt = datetime.fromtimestamp(run["start_uts"], tz=timezone.utc).astimezone(KST)
    end_dt = datetime.fromtimestamp(run["end_uts"], tz=timezone.utc).astimezone(KST)
    dates = set()
    d = start_dt.date()
    while True:
        dates.add(d.strftime("%Y-%m-%d"))
        if d == end_dt.date():
            break
        d = d + timedelta(days=1)
    return sum(apple_counts.get((run["track"], d), 0) for d in dates)


def classify_run(run, name_to_durations, apple_durations, apple_counts, have_apple_log,
                log_end_uts=None, catalog_index=None):
    match = duration_match(run, name_to_durations, apple_durations)
    run["duration_match"] = match

    if match is not True:
        if match is None:
            # 곡 길이 정보 자체가 없어 확인 불가. 그래도 간격이 완전히 동일하게
            # 반복된 것은 사실이므로(=이 버그와 같은 패턴), 가장 오래된(가장 이른
            # 시각) 기록 하나만 진짜로 보고 남기고 나머지는 중복으로 제거한다.
            run["classification"] = "UNVERIFIABLE"
            run["apple_count_same_day"] = None
            run["rows_to_keep"] = [run["row_ids"][0]]
            run["rows_to_remove"] = run["row_ids"][1:]
        else:
            # 간격이 그 곡의 실제 재생시간과 일치하지 않음 -> 이 버그와 무관한
            # 우연한 반복(진짜 재청취)으로 보고 전부 남긴다.
            run["classification"] = "KEEP_NO_MATCH"
            run["apple_count_same_day"] = None
            run["rows_to_remove"] = []
            run["rows_to_keep"] = list(run["row_ids"])
        return run

    if not have_apple_log:
        run["classification"] = "UNVERIFIABLE"
        run["apple_count_same_day"] = None
        run["rows_to_remove"] = []
        run["rows_to_keep"] = list(run["row_ids"])
        return run

    if log_end_uts is not None and run["end_uts"] > log_end_uts:
        # 애플 로그가 끝난 뒤(또는 걸쳐 있는) 구간: 대조할 로그가 없으므로
        # REMOVE/PARTIAL로 판정하면 진짜 재생까지 통째로 지우게 된다.
        # 간격-곡길이 지문은 일치하므로 (B) 패턴(시작+계산된 종료 2줄)으로 보고,
        # 가장 이른 기록 하나만 진짜로 남긴다 (곡 길이를 모르는 UNVERIFIABLE과 동일).
        run["classification"] = "UNVERIFIABLE"
        run["apple_count_same_day"] = None
        run["rows_to_keep"] = [run["row_ids"][0]]
        run["rows_to_remove"] = run["row_ids"][1:]
        return run

    if catalog_index is not None and catalog_index.is_noncatalog(run.get("artist", ""), run["track"]):
        # Last.fm 기록이 기준이다. 애플 로그가 원래 기록하지 못하는 곡은 "로그에 없음"을
        # 가짜의 증거로 쓸 수 없으므로 확인 불가로 두고, 아무것도 지우지 않는다.
        run["classification"] = "UNVERIFIABLE"
        run["apple_count_same_day"] = None
        run["rows_to_remove"] = []
        run["rows_to_keep"] = list(run["row_ids"])
        run["reason"] = "noncatalog"
        return run

    ac = apple_corroboration_count(run, apple_counts)
    run["apple_count_same_day"] = ac
    n = run["count"]

    if ac == 0:
        run["classification"] = "REMOVE"
        run["rows_to_remove"] = list(run["row_ids"])
        run["rows_to_keep"] = []
    elif ac >= n:
        run["classification"] = "KEEP"
        run["rows_to_remove"] = []
        run["rows_to_keep"] = list(run["row_ids"])
    else:
        run["classification"] = "PARTIAL_DUPLICATE"
        # 시간순으로 앞에서부터 ac개만 "진짜"로 보고 남기고, 나머지는 중복으로 제거
        run["rows_to_keep"] = list(run["row_ids"][:ac])
        run["rows_to_remove"] = list(run["row_ids"][ac:])

    return run


# ---------------------------------------------------------------------------
# 4. 행 단위 판정 결과 만들기
# ---------------------------------------------------------------------------

def build_row_verdicts(scrobble_rows, all_runs):
    """모든 원본 행에 대해 verdict, reason, run 정보를 붙인다."""
    row_to_run = {}
    for run in all_runs:
        for rid in run["rows_to_remove"]:
            row_to_run[rid] = ("REMOVE", run)
        for rid in run["rows_to_keep"]:
            if run["classification"] in ("REMOVE",):
                continue
            # PARTIAL_DUPLICATE의 남는 행, KEEP/KEEP_NO_MATCH/UNVERIFIABLE 행
            if rid not in row_to_run:
                row_to_run[rid] = (
                    "KEEP" if run["classification"] in ("KEEP", "KEEP_NO_MATCH") else run["classification"],
                    run,
                )

    results = []
    for r in scrobble_rows:
        verdict, run = row_to_run.get(r["row_id"], ("KEEP", None))
        results.append({
            "row_id": r["row_id"],
            "uts": r["uts"],
            "artist": r["artist"],
            "track": r["track"],
            "album": r["album"],
            "source": r["source"],
            "verdict": verdict,
            "run_gap": run["gap"] if run else "",
            "run_count": run["count"] if run else "",
            "apple_count_same_day": run.get("apple_count_same_day", "") if run else "",
        })
    return results


# ---------------------------------------------------------------------------
# 5. 출력
# ---------------------------------------------------------------------------

def write_run_audit_csv(all_runs, out_path):
    fieldnames = ["artist", "track", "start_kst", "end_kst", "count", "gap_seconds",
                  "classification", "duration_match", "apple_count_same_day",
                  "n_removed", "n_kept"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in sorted(all_runs, key=lambda x: -x["count"]):
            sdt = datetime.fromtimestamp(r["start_uts"], tz=timezone.utc).astimezone(KST)
            edt = datetime.fromtimestamp(r["end_uts"], tz=timezone.utc).astimezone(KST)
            w.writerow({
                "artist": r["artist"], "track": r["track"],
                "start_kst": sdt.strftime("%Y-%m-%d %H:%M:%S"),
                "end_kst": edt.strftime("%Y-%m-%d %H:%M:%S"),
                "count": r["count"], "gap_seconds": r["gap"],
                "classification": r["classification"],
                "duration_match": r.get("duration_match"),
                "apple_count_same_day": r.get("apple_count_same_day"),
                "n_removed": len(r["rows_to_remove"]), "n_kept": len(r["rows_to_keep"]),
            })


def write_row_verdicts_csv(row_verdicts, out_path):
    fieldnames = ["row_id", "uts", "utc_kst", "artist", "track", "album", "source",
                  "verdict", "run_gap", "run_count", "apple_count_same_day"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in row_verdicts:
            dt = datetime.fromtimestamp(r["uts"], tz=timezone.utc).astimezone(KST)
            w.writerow({**r, "utc_kst": dt.strftime("%Y-%m-%d %H:%M:%S")})


def write_period_report(row_verdicts, out_path, scrobbles_path):
    bad = [r for r in row_verdicts if r["verdict"] in ("REMOVE", "PARTIAL_DUPLICATE")]
    total = len(row_verdicts)

    by_month = defaultdict(lambda: {"REMOVE": 0, "PARTIAL_DUPLICATE": 0, "total": 0})
    for r in row_verdicts:
        dt = datetime.fromtimestamp(r["uts"], tz=timezone.utc).astimezone(KST)
        key = dt.strftime("%Y-%m")
        by_month[key]["total"] += 1
        if r["verdict"] in ("REMOVE", "PARTIAL_DUPLICATE"):
            by_month[key][r["verdict"]] += 1

    lines = []
    lines.append("# last.fm 스크로블 이상 기록 감사 리포트\n")
    lines.append(f"- 대상 파일: `{scrobbles_path}`")
    lines.append(f"- 생성 시각(KST): {datetime.now(tz=KST).strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"- 전체 행 수: {total}")
    n_remove = sum(1 for r in row_verdicts if r["verdict"] == "REMOVE")
    n_dup = sum(1 for r in row_verdicts if r["verdict"] == "PARTIAL_DUPLICATE")
    n_keep = sum(1 for r in row_verdicts if r["verdict"] == "KEEP")
    n_unver = sum(1 for r in row_verdicts if r["verdict"] == "UNVERIFIABLE")
    lines.append(f"- 완전 허구로 판정 (REMOVE): {n_remove}행 ({n_remove/total*100:.1f}%)")
    lines.append(f"- 중복 기록으로 판정 (PARTIAL_DUPLICATE, 애플 실제 재생 수만큼만 인정): {n_dup}행 ({n_dup/total*100:.1f}%)")
    lines.append(f"- 정상으로 판정 (KEEP): {n_keep}행 ({n_keep/total*100:.1f}%)")
    lines.append(f"- 판단 근거 부족 (UNVERIFIABLE, 그대로 둠): {n_unver}행 ({n_unver/total*100:.1f}%)")
    lines.append("")
    lines.append("## 월별 발생 현황 (KST 기준)\n")
    lines.append("| 월 | 전체 스크로블 | REMOVE(완전 허구) | PARTIAL_DUPLICATE(중복) | 문제 비율 |")
    lines.append("|---|---:|---:|---:|---:|")
    for month in sorted(by_month.keys()):
        d = by_month[month]
        bad_n = d["REMOVE"] + d["PARTIAL_DUPLICATE"]
        pct = bad_n / d["total"] * 100 if d["total"] else 0
        lines.append(f"| {month} | {d['total']} | {d['REMOVE']} | {d['PARTIAL_DUPLICATE']} | {pct:.1f}% |")

    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def apply_removal(scrobbles_path, remove_row_ids):
    with open(scrobbles_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        rows = list(reader)

    kept = [r for i, r in enumerate(rows) if i not in remove_row_ids]
    removed = len(rows) - len(kept)

    backup_path = scrobbles_path + ".bak"
    shutil.copy2(scrobbles_path, backup_path)

    tmp_path = scrobbles_path + ".tmp"
    with open(tmp_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(kept)
    os.replace(tmp_path, scrobbles_path)
    return removed, len(rows), len(kept), backup_path


# ---------------------------------------------------------------------------
# 6. 메인
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="last.fm 스크로블 중 애플 뮤직 백필/중복 기록 탐지")
    parser.add_argument("--scrobbles", required=True)
    parser.add_argument("--apple-activity", default=None)
    parser.add_argument("--library-xml", default=None)
    parser.add_argument("--library-json", default=None,
                        help="Apple Music Library Tracks.json(.zip). 생략하면 --apple-activity 와 같은 폴더에서 찾는다")
    parser.add_argument("--no-catalog-check", action="store_true",
                        help="카탈로그 식별자 없는 곡을 로그 규칙에서 빼는 예외를 끈다 (이전 동작)")
    parser.add_argument("--source-filter", default=None, help="이 값과 source 열이 일치하는 행만 검사 (예: L)")
    parser.add_argument("--run-output", default=None, help="구간(run) 단위 감사 리포트 CSV 경로")
    parser.add_argument("--row-output", default=None, help="행 단위 판정 결과 CSV 경로")
    parser.add_argument("--report", default=None, help="기간별 발생 현황 마크다운 리포트 경로")
    parser.add_argument("--apply", action="store_true", help="REMOVE/PARTIAL_DUPLICATE 판정 행을 실제로 삭제")
    args = parser.parse_args()

    print(f"스크로블 로딩: {args.scrobbles}")
    scrobble_rows = load_scrobbles(args.scrobbles, source_filter=args.source_filter)
    print(f"  -> 검사 대상 {len(scrobble_rows)}행")

    all_runs = build_runs_by_track(scrobble_rows)
    print(f"완전 동일 간격 반복 구간(2회 이상): {len(all_runs)}개")

    name_to_durations = load_library_durations(args.library_xml)
    needed_tracks = {r["track"] for r in all_runs}
    apple_counts, apple_durations, log_end_uts = load_apple_activity(args.apple_activity, needed_tracks)
    have_apple_log = bool(args.apple_activity and os.path.exists(args.apple_activity))
    if log_end_uts is not None:
        print("애플 로그 종료 시각(KST): "
              + datetime.fromtimestamp(log_end_uts, tz=timezone.utc).astimezone(KST).strftime("%Y-%m-%d %H:%M:%S"))

    catalog_index = None
    if have_apple_log and not args.no_catalog_check:
        lib_json = args.library_json or os.path.join(
            os.path.dirname(os.path.abspath(args.apple_activity)), "Apple Music Library Tracks.json.zip")
        catalog_index = load_catalog_index(lib_json)
        if catalog_index is None:
            print("경고: Apple 라이브러리 JSON 을 못 찾아 카탈로그 확인을 건너뜁니다 "
                  "(카탈로그 없는 곡도 로그 규칙으로 판정됨). --library-json 으로 지정하세요.")
        else:
            n_non = sum(1 for v in catalog_index.by_artist_title.values() if not v)
            print(f"카탈로그 확인: 라이브러리에서 카탈로그 식별자가 없는 곡 {n_non}개는 로그 규칙에서 제외(확인 불가)")

    for run in all_runs:
        classify_run(run, name_to_durations, apple_durations, apple_counts, have_apple_log,
                     log_end_uts, catalog_index)

    row_verdicts = build_row_verdicts(scrobble_rows, all_runs)

    vc = Counter(r["verdict"] for r in row_verdicts)
    print()
    print("=== 최종 행 단위 판정 ===")
    for v in ("KEEP", "PARTIAL_DUPLICATE", "REMOVE", "UNVERIFIABLE"):
        print(f"  {v:<18} {vc.get(v, 0)}행")

    if args.run_output:
        write_run_audit_csv(all_runs, args.run_output)
        print(f"\n구간 단위 리포트: {args.run_output}")
    if args.row_output:
        write_row_verdicts_csv(row_verdicts, args.row_output)
        print(f"행 단위 판정 결과: {args.row_output}")
    if args.report:
        write_period_report(row_verdicts, args.report, args.scrobbles)
        print(f"기간별 발생 리포트: {args.report}")

    if args.apply:
        # 주의: verdict == "PARTIAL_DUPLICATE"는 "중복 중에서 남기기로 한
        # 진짜 1건"을 뜻하므로 삭제 대상이 아니다. 삭제 대상은 verdict == "REMOVE"뿐.
        remove_ids = {r["row_id"] for r in row_verdicts if r["verdict"] == "REMOVE"}
        removed, before, after, backup = apply_removal(args.scrobbles, remove_ids)
        print(f"\n원본 백업: {backup}")
        print(f"삭제 적용: {before}행 -> {after}행 ({removed}행 제거)")


if __name__ == "__main__":
    main()
