# -*- coding: utf-8 -*-
"""
normalize_artists.py

Apple 기록(A)과 Last.fm 기록(L)이 같은 아티스트를 대소문자·띄어쓰기만 다르게 적어서
(예: Have A Nice Life / Have a Nice Life) 앱이 서로 다른 아티스트로 세는 문제를 고친다.
통일할 이름은 **Last.fm(L)이 쓰는 표기**다.

규칙
----
  - 합치는 대상: NFKC + 소문자 + 공백 제거한 키가 같은 이름들. 이 키는 구두점·괄호·feat. 를
    바꾸지 않으므로 "OutKast"와 "Outkast featuring ..." 같은 이름이나 공동 크레딧은 합치지 않는다.
  - 통일 이름: 묶음 안에서 L 행에 가장 많이 쓰인 표기 (동률이면 전체 행 수, 그다음 사전순).
    L 행이 하나도 없는 묶음은 Last.fm 표기를 알 수 없으므로 건드리지 않는다.
  - config/artist_keep_separate.txt 에 적힌 이름은 합치기에서 제외한다 (이름 변경도, 통일 이름 후보도 아님).
  - source 열은 바꾸지 않는다. 기본은 dry-run, --apply 를 주면 백업(.bak_artistnorm_*)을 만들고
    data/artist_normalize_log.csv 에 바뀐 행을 남기며 config/artist_canonical.txt(변형 -> 통일 이름)를
    갱신한다. 제거 기록(preprocess_removed.csv)의 artist 도 같은 규칙으로 맞춘다.

사용법
------
    python3 scripts/normalize_artists.py            # dry-run
    python3 scripts/normalize_artists.py --apply
"""

import argparse
import csv
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import preprocess as pp  # noqa: E402  (read_csv / write_csv_atomic 재사용)

ROOT = SCRIPT_DIR.parent
KEEP_SEPARATE_FILE = ROOT / "config" / "artist_keep_separate.txt"
CANONICAL_FILE = ROOT / "config" / "artist_canonical.txt"
LOG_FIELDS = ["uts", "utc_time", "track", "source", "old_artist", "new_artist", "rule", "changed_at"]


def simple_key(name):
    """대소문자·띄어쓰기만 무시하는 비교 키."""
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", str(name)).lower())


def load_keep_separate(path):
    names = set()
    if path and Path(path).exists():
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                names.add(line)
    return names


def build_mapping(stats, keep_separate=frozenset()):
    """
    stats: {아티스트: {"A": 행 수, "L": 행 수}}
    반환: (mapping {변형: 통일 이름}, groups [(통일 이름, [변형들])], skipped_no_lastfm [묶음])
    """
    by_key = defaultdict(list)
    for name in stats:
        if not name or name in keep_separate:
            continue
        by_key[simple_key(name)].append(name)
    mapping, groups, skipped = {}, [], []
    for names in by_key.values():
        if len(names) < 2:
            continue
        l_counts = {n: stats[n].get("L", 0) for n in names}
        if not any(l_counts.values()):
            skipped.append(sorted(names))                       # Last.fm 표기를 알 수 없음
            continue
        canonical = sorted(names, key=lambda n: (-l_counts[n], -(stats[n].get("A", 0) + l_counts[n]), n))[0]
        variants = sorted(n for n in names if n != canonical)
        for v in variants:
            mapping[v] = canonical
        groups.append((canonical, variants))
    return mapping, groups, skipped


def main():
    ap = argparse.ArgumentParser(description="아티스트 표기를 Last.fm 표기로 통일 (기본 dry-run)")
    ap.add_argument("--data-dir", default=str(pp.DEFAULT_DATA_DIR))
    ap.add_argument("--keep-separate", default=str(KEEP_SEPARATE_FILE))
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    csv_path = pp.find_data_csv(args.data_dir)
    if not csv_path:
        raise SystemExit("data 폴더에 *_scrobbles.csv 가 없습니다.")
    header, rows = pp.read_csv(csv_path)

    stats = defaultdict(lambda: {"A": 0, "L": 0})
    for r in rows:
        if r.get("artist"):
            stats[r["artist"]][r.get("source", "L")] += 1
    keep = load_keep_separate(args.keep_separate)
    mapping, groups, skipped = build_mapping(stats, keep)

    changed = Counter()
    for r in rows:
        if r.get("artist") in mapping:
            changed[r.get("source", "L")] += 1
    print(f"[{'apply' if args.apply else 'dry-run'}] {csv_path.name}: 합칠 묶음 {len(groups)}개, 이름이 바뀌는 행 {sum(changed.values())} "
          f"(A {changed['A']}, L {changed['L']})")
    print(f"  예외(그대로 둠): {sorted(keep)}")
    if skipped:
        print(f"  Last.fm 표기가 없어 건드리지 않은 묶음: {skipped}")
    print("  통일 결과 (변형 -> 통일 이름, 바뀌는 행 수):")
    for canonical, variants in sorted(groups, key=lambda g: -sum(stats[v]["A"] + stats[v]["L"] for v in g[1])):
        for v in variants:
            print(f"    '{v}' -> '{canonical}'  ({stats[v]['A'] + stats[v]['L']}행)")
    if not args.apply:
        print("  (dry-run: 파일은 수정하지 않았습니다. 반영하려면 --apply)")
        return

    new_rows = []
    keys = set()
    for r in rows:
        nr = dict(r)
        if nr.get("artist") in mapping:
            nr["artist"] = mapping[nr["artist"]]
        k = (nr["uts"], nr["artist"], nr["track"])
        if k in keys:
            raise SystemExit(f"이름을 바꾸면 같은 키(uts+artist+track)가 중복됩니다: {k} — 중단합니다.")
        keys.add(k)
        new_rows.append(nr)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = csv_path.with_name(csv_path.name + f".bak_artistnorm_{stamp}")
    shutil.copy2(csv_path, backup)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = Path(args.data_dir) / "artist_normalize_log.csv"
    old_log = []
    if log_path.exists():
        with open(log_path, newline="", encoding="utf-8-sig") as f:
            old_log = list(csv.DictReader(f))
    new_log = [{"uts": r["uts"], "utc_time": r.get("utc_time", ""), "track": r["track"], "source": r.get("source", ""),
                "old_artist": r["artist"], "new_artist": mapping[r["artist"]], "rule": "case_space_to_lastfm",
                "changed_at": now} for r in rows if r.get("artist") in mapping]
    pp.write_csv_atomic(csv_path, header, new_rows)
    pp.write_csv_atomic(log_path, LOG_FIELDS, old_log + new_log)

    # 제거 기록의 artist 도 같은 이름으로 맞춘다 (나중에 provisional 행을 되살릴 때 표기가 다시 갈라지지 않게)
    ledger_path = Path(args.data_dir) / "preprocess_removed.csv"
    n_ledger = 0
    if ledger_path.exists():
        with open(ledger_path, newline="", encoding="utf-8-sig") as f:
            ledger = list(csv.DictReader(f))
        for r in ledger:
            if r.get("artist") in mapping:
                r["artist"] = mapping[r["artist"]]
                n_ledger += 1
        if n_ledger:
            pp.write_csv_atomic(ledger_path, pp.LEDGER_FIELDS, ledger)

    # 이전 실행에서 적용한 변형도 보존하도록 기존 목록에 합친다 (덮어쓰면 앞선 기록이 사라진다)
    merged = {}
    if CANONICAL_FILE.exists():
        for line in CANONICAL_FILE.read_text(encoding="utf-8").splitlines():
            if "->" in line and not line.lstrip().startswith("#"):
                v, c = line.split("->", 1)
                merged[v.strip()] = c.strip()
    merged.update(mapping)
    lines = ["# normalize_artists.py 가 만든 목록: 변형 -> Last.fm 표기 (대소문자·띄어쓰기만 다른 이름)"]
    lines += [f"{v} -> {c}" for v, c in sorted(merged.items())]
    CANONICAL_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  반영 완료: {len(new_log)}행 (백업: {backup.name}, 기록: {log_path.name}, 설정: config/{CANONICAL_FILE.name}, "
          f"제거 기록 {n_ledger}행 갱신)")


if __name__ == "__main__":
    main()
