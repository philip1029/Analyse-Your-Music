# -*- coding: utf-8 -*-
"""
normalize_titles.py

Apple 기록(A)과 Last.fm 기록(L)이 같은 곡/앨범 제목을 대소문자·띄어쓰기만 다르게 적어서
(예: "Shine On You Crazy Diamond" / "Shine on You Crazy Diamond") 앱이 서로 다른 곡으로 세는 문제를 고친다.
통일할 표기는 **Last.fm(L)이 쓰는 표기**다. (normalize_artists.py 의 곡/앨범 버전)

규칙
----
  - 같은 아티스트(표기가 정확히 같은 행들) 안에서만 비교한다. 다른 아티스트의 같은 이름 곡은 건드리지 않는다.
  - 합치는 대상: NFKC + 소문자 + 공백 제거한 키가 같은 제목들 (… 와 ..., 전각/반각 문자도 같은 제목으로 본다).
    구두점·괄호·feat. 는 지우지 않으므로 "Intro"와 "Intro (Live)" 같은 다른 제목은 합치지 않는다.
  - 통일 표기: 묶음 안에서 L 행에 가장 많이 쓰인 표기 (동률이면 전체 행 수, 그다음 사전순).
    L 행이 하나도 없는 묶음은 Last.fm 표기를 알 수 없으므로 건드리지 않는다.
  - source 열은 바꾸지 않는다. 기본은 dry-run, --apply 를 주면 백업(.bak_titlenorm_*)을 만들고
    data/title_normalize_log.csv 에 바뀐 행을 남긴다. 제거 기록(preprocess_removed.csv)의 제목도 같은
    규칙으로 맞춘다. 바꾼 뒤 같은 키(uts+artist+track)가 중복되면 아무것도 쓰지 않고 중단한다.

사용법
------
    python3 scripts/normalize_titles.py            # dry-run
    python3 scripts/normalize_titles.py --apply
    python3 scripts/normalize_titles.py --apply --json   # 결과를 JSON 한 줄로 (최신 스크롭 불러오기 버튼이 사용)

바꿀 행이 없으면 --apply 여도 백업·기록·파일 쓰기를 하지 않는다 (버튼을 누를 때마다 백업이 쌓이지 않도록).
"""

import argparse
import csv
import json
import shutil
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import preprocess as pp  # noqa: E402  (read_csv / write_csv_atomic 재사용)
from normalize_artists import simple_key  # noqa: E402

FIELDS = ("track", "album")
LOG_FIELDS = ["uts", "utc_time", "artist", "source", "field", "old_title", "new_title", "rule", "changed_at"]


def build_title_mapping(rows, field):
    """
    반환: (mapping {(아티스트, 변형): 통일 표기}, groups [(아티스트, 통일 표기, [변형들])], skipped [(아티스트, [표기들])])
    """
    stats = defaultdict(lambda: defaultdict(lambda: {"A": 0, "L": 0}))     # (아티스트, 키) -> 표기 -> 소스별 행 수
    for r in rows:
        t = r.get(field, "")
        if t:
            stats[(r.get("artist", ""), simple_key(t))][t][r.get("source", "L")] += 1
    mapping, groups, skipped = {}, [], []
    for (artist, _), titles in stats.items():
        if len(titles) < 2:
            continue
        l_count = {t: s["L"] for t, s in titles.items()}
        if not any(l_count.values()):
            skipped.append((artist, sorted(titles)))
            continue
        total = {t: s["A"] + s["L"] for t, s in titles.items()}
        canonical = sorted(titles, key=lambda t: (-l_count[t], -total[t], t))[0]
        variants = sorted(t for t in titles if t != canonical)
        for v in variants:
            mapping[(artist, v)] = canonical
        groups.append((artist, canonical, variants))
    return mapping, groups, skipped


def main():
    ap = argparse.ArgumentParser(description="곡/앨범 제목 표기를 Last.fm 표기로 통일 (기본 dry-run)")
    ap.add_argument("--data-dir", default=str(pp.DEFAULT_DATA_DIR))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true", help="결과를 JSON 한 줄로만 출력")
    args = ap.parse_args()

    csv_path = pp.find_data_csv(args.data_dir)
    if not csv_path:
        raise SystemExit("data 폴더에 *_scrobbles.csv 가 없습니다.")
    header, rows = pp.read_csv(csv_path)

    maps, groups, skipped = {}, {}, {}
    for f in FIELDS:
        maps[f], groups[f], skipped[f] = build_title_mapping(rows, f)

    changed = {f: Counter() for f in FIELDS}
    for r in rows:
        for f in FIELDS:
            if (r.get("artist", ""), r.get(f, "")) in maps[f]:
                changed[f][r.get("source", "L")] += 1
    n_changed = {f: sum(changed[f].values()) for f in FIELDS}
    result = {"applied": False, "tracks": n_changed["track"], "albums": n_changed["album"], "backup": None}
    if not args.json:
        print(f"[{'apply' if args.apply else 'dry-run'}] {csv_path.name}")
        for f in FIELDS:
            print(f"  {f}: 합칠 묶음 {len(groups[f])}개, 이름이 바뀌는 행 {n_changed[f]} (A {changed[f]['A']}, L {changed[f]['L']}), "
                  f"Last.fm 표기가 없어 건드리지 않은 묶음 {len(skipped[f])}개")
            top = sorted(groups[f], key=lambda g: -sum(1 for r in rows if r.get("artist", "") == g[0] and r.get(f) in g[2]))[:8]
            for artist, canonical, variants in top:
                print(f"    [{artist[:24]}] {variants} -> '{canonical}'")
    if not args.apply or not any(n_changed.values()):
        if args.json:
            print(json.dumps(result, ensure_ascii=False))
        elif not args.apply:
            print("  (dry-run: 파일은 수정하지 않았습니다. 반영하려면 --apply)")
        else:
            print("  바꿀 행이 없어 파일을 수정하지 않았습니다.")
        return

    new_rows, keys, log = [], set(), []
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    for r in rows:
        nr = dict(r)
        for f in FIELDS:
            new = maps[f].get((r.get("artist", ""), r.get(f, "")))
            if new:
                nr[f] = new
                log.append({"uts": r["uts"], "utc_time": r.get("utc_time", ""), "artist": r.get("artist", ""), "source": r.get("source", ""),
                            "field": f, "old_title": r[f], "new_title": new, "rule": "case_space_to_lastfm", "changed_at": now})
        k = (nr["uts"], nr.get("artist", ""), nr["track"])
        if k in keys:
            raise SystemExit(f"이름을 바꾸면 같은 키(uts+artist+track)가 중복됩니다: {k} — 아무것도 쓰지 않고 중단합니다.")
        keys.add(k)
        new_rows.append(nr)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = csv_path.with_name(csv_path.name + f".bak_titlenorm_{stamp}")
    shutil.copy2(csv_path, backup)
    log_path = Path(args.data_dir) / "title_normalize_log.csv"
    old_log = []
    if log_path.exists():
        with open(log_path, newline="", encoding="utf-8-sig") as fh:
            old_log = list(csv.DictReader(fh))
    pp.write_csv_atomic(csv_path, header, new_rows)
    pp.write_csv_atomic(log_path, LOG_FIELDS, old_log + log)

    # 제거 기록의 제목도 맞춘다 (나중에 provisional 행을 되살릴 때 표기가 다시 갈라지지 않게)
    ledger_path = Path(args.data_dir) / "preprocess_removed.csv"
    n_ledger = 0
    if ledger_path.exists():
        with open(ledger_path, newline="", encoding="utf-8-sig") as fh:
            ledger = list(csv.DictReader(fh))
        for r in ledger:
            for f in FIELDS:
                new = maps[f].get((r.get("artist", ""), r.get(f, "")))
                if new:
                    r[f] = new
                    n_ledger += 1
        if n_ledger:
            pp.write_csv_atomic(ledger_path, pp.LEDGER_FIELDS, ledger)
    result.update(applied=True, backup=backup.name, ledger=n_ledger)
    if args.json:
        print(json.dumps(result, ensure_ascii=False))
    else:
        print(f"  반영 완료: {len(log)}건 (백업: {backup.name}, 기록: {log_path.name}, 제거 기록 {n_ledger}건 갱신)")


if __name__ == "__main__":
    main()
