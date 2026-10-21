# -*- coding: utf-8 -*-
"""
fill_missing_artists.py

애플 재생 로그에서 만든 A 소스 행 중 아티스트가 빈 행(스트리밍으로만 들어서
라이브러리/컨테이너 조회에 안 잡힌 곡)을 채운다.

근거: 애플 데이터의 "Apple Music - Play History Daily Tracks.csv" 는 Track Description 이
"아티스트 - 곡명" 형태라서 곡명으로 아티스트를 읽을 수 있다. 내 청취 기록에서 나온 행이므로
같은 곡이 이 파일에도 있어야 한다는 전제를 쓴다.

규칙
----
  - source == "A" 이고 artist 가 빈 행만 대상 (L 행과 이미 채워진 행은 건드리지 않는다)
  - 곡명이 정확히 한 아티스트에만 대응하면 채운다.
    여러 아티스트에 대응(예: Diana = Comus / Skip Spence)하거나 파일에 없으면 비워 둔다.
  - --set "곡명=아티스트" 로 수동 지정할 수 있다 (수동 지정은 규칙보다 우선).
기본은 dry-run. --apply 를 주면 백업(.bak_artistfill_*)을 만들고 data/artist_fill_log.csv 에
행마다 이전 값/새 값/규칙을 남긴다. source 열은 바꾸지 않는다.

사용법
------
    python3 scripts/fill_missing_artists.py --apple-dir "<Apple Music Activity 폴더>"
    python3 scripts/fill_missing_artists.py --apple-dir "<...>" --set "Soon=My Bloody Valentine" --apply
"""

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
import preprocess as pp  # noqa: E402  (read_csv / write_csv_atomic 재사용)
from csv_backup import make_backup  # noqa: E402

LOG_FIELDS = ["uts", "utc_time", "track", "old_artist", "new_artist", "old_album", "new_album",
              "rule", "filled_at"]


def load_title_to_artists(apple_dir):
    path = Path(apple_dir) / "Apple Music - Play History Daily Tracks.csv"
    if not path.exists():
        raise SystemExit(f"파일이 없습니다: {path}")
    mapping = defaultdict(set)
    with open(path, newline="", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            desc = (row.get("Track Description") or "").strip()
            if " - " not in desc:
                continue
            artist, title = desc.split(" - ", 1)
            if artist and title:
                mapping[title].add(artist)
    return mapping


def main():
    ap = argparse.ArgumentParser(description="A 소스의 빈 artist 채우기 (기본 dry-run)")
    ap.add_argument("--data-dir", default=str(pp.DEFAULT_DATA_DIR))
    ap.add_argument("--apple-dir", required=True)
    ap.add_argument("--set", action="append", default=[], metavar="곡명=아티스트",
                    help="수동 지정 (여러 번 가능)")
    ap.add_argument("--set-album", action="append", default=[], metavar="곡명=앨범",
                    help="앨범이 빈 A 행의 앨범 수동 지정 (여러 번 가능)")
    ap.add_argument("--album-unique", action="store_true",
                    help="그래도 빈 행은 같은 앨범의 다른 행에 아티스트가 정확히 한 명뿐일 때 그 아티스트로 채운다")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    def parse_pairs(items, flag):
        out = {}
        for item in items:
            if "=" not in item:
                raise SystemExit(f"{flag} 형식은 '곡명=값' 입니다: {item}")
            t, v = item.split("=", 1)
            out[t.strip()] = v.strip()
        return out

    manual = parse_pairs(args.set, "--set")
    manual_album = parse_pairs(args.set_album, "--set-album")

    csv_path = pp.find_data_csv(args.data_dir)
    if not csv_path:
        raise SystemExit("data 폴더에 *_scrobbles.csv 가 없습니다.")
    header, rows = pp.read_csv(csv_path)
    mapping = load_title_to_artists(args.apple_dir)

    # 앨범 -> 이미 아티스트가 채워진 행들의 아티스트 집합 (album_unique 규칙의 근거)
    album_artists = defaultdict(set)
    for r in rows:
        a, al = (r.get("artist") or "").strip(), (r.get("album") or "").strip()
        if a and al:
            album_artists[al].add(a)

    # changes: {행 인덱스: {"artist": 새 값 또는 None, "album": 새 값 또는 None, "rule": ...}}
    changes, ambiguous, missing = {}, 0, 0
    for i, r in enumerate(rows):
        if r.get("source") != "A":
            continue
        t = r["track"]
        if not (r.get("artist") or "").strip():
            al = (r.get("album") or "").strip()
            if t in manual:
                changes[i] = {"artist": manual[t], "album": None, "rule": "manual"}
            elif t in mapping and len(mapping[t]) == 1:
                changes[i] = {"artist": next(iter(mapping[t])), "album": None,
                              "rule": "daily_tracks:unique_title"}
            elif args.album_unique and al and len(album_artists.get(al, ())) == 1:
                changes[i] = {"artist": next(iter(album_artists[al])), "album": None,
                              "rule": "album_unique"}
            elif t in mapping:
                ambiguous += 1
            else:
                missing += 1
        if not (r.get("album") or "").strip() and t in manual_album:
            c = changes.setdefault(i, {"artist": None, "album": None, "rule": "manual"})
            c["album"] = manual_album[t]

    by_rule = defaultdict(int)
    for c in changes.values():
        by_rule[c["rule"]] += 1
    total_empty = sum(1 for r in rows if r.get("source") == "A" and not (r.get("artist") or "").strip())
    print(f"[{'apply' if args.apply else 'dry-run'}] {csv_path.name}: A 소스 빈 artist {total_empty}행")
    print(f"  채울 행: {len(changes)} {dict(by_rule)}")
    print(f"  비워 둠: 곡명에 아티스트가 여럿 {ambiguous} / 파일에 없음 {missing}")
    for t, a in manual.items():
        n = sum(1 for i, c in changes.items() if c["artist"] == a and rows[i]["track"] == t and c["rule"] == "manual")
        print(f"  수동 지정 artist '{t}' -> '{a}': {n}행")
    for t, a in manual_album.items():
        n = sum(1 for i, c in changes.items() if c["album"] == a and rows[i]["track"] == t)
        print(f"  수동 지정 album  '{t}' -> '{a}': {n}행")
    if not args.apply:
        print("  (dry-run: 파일은 수정하지 않았습니다. 반영하려면 --apply)")
        return
    if not changes:
        print("  변경할 행이 없습니다.")
        return

    backup = make_backup(csv_path, "artistfill")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_path = Path(args.data_dir) / "artist_fill_log.csv"
    old_log = []
    if log_path.exists():
        with open(log_path, newline="", encoding="utf-8-sig") as f:
            old_log = list(csv.DictReader(f))
    new_log = []
    for i, c in changes.items():
        r = rows[i]
        new_log.append({"uts": r["uts"], "utc_time": r.get("utc_time", ""), "track": r["track"],
                        "old_artist": r.get("artist", ""), "new_artist": c["artist"] or "",
                        "old_album": r.get("album", ""), "new_album": c["album"] or "",
                        "rule": c["rule"], "filled_at": now})
        if c["artist"] is not None:
            r["artist"] = c["artist"]
        if c["album"] is not None:
            r["album"] = c["album"]
    pp.write_csv_atomic(csv_path, header, rows)
    pp.write_csv_atomic(log_path, LOG_FIELDS, old_log + new_log)
    print(f"  반영 완료: {len(changes)}행 (백업: {backup.name}, 변경 기록: {log_path.name})")


if __name__ == "__main__":
    main()
