"""
'곡명 - 아티스트' 목록(한 줄에 하나)을 좋아요(♥) 곡으로 가져온다. 기본은 어떻게 매칭되는지만 보여 주는 dry-run 이고,
--apply 를 주면 data/favorites.json 에 저장한다 (저장 전에 기존 파일을 .bak 으로 백업).

  python3 scripts/import_favorites.py list.txt            # 확인만
  python3 scripts/import_favorites.py list.txt --apply    # 매칭된 곡만 저장

곡명이 기록과 다르게 적힌 곡(원어/로마자 표기 차이 등)은 "못 찾음"으로 나온다. 그런 곡은 앱에서 직접 찾아 ♥ 를 누르면 된다.
같은 이름의 곡이 여러 아티스트에 있어 하나로 못 정하면 "애매함"으로 나오고 저장하지 않는다.
"""

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

import pandas as pd  # noqa: E402

from app.analysis import favorites  # noqa: E402


def load_df(data_dir: Path) -> pd.DataFrame:
    files = sorted(data_dir.glob("*_scrobbles.csv"))
    if not files:
        raise SystemExit("data 폴더에 scrobbles csv 가 없습니다.")
    df = pd.read_csv(files[0], encoding="utf-8-sig")
    df[["artist", "album", "track"]] = df[["artist", "album", "track"]].fillna("")
    return df.drop_duplicates(subset=["uts", "artist", "track"], keep="first")


def match_lines(df: pd.DataFrame, lines: list[str]) -> list[dict]:
    nk = favorites.track_keys(df)
    results = []
    for line in lines:
        parsed = favorites.parse_line(line)
        if not parsed:
            continue
        title, artist = parsed
        cands = favorites.find_track(df, title, artist, nk)
        if not cands and artist:
            # 아티스트를 뺀 전체 줄이 곡명인 경우 (제목에 " - " 가 들어 있는 곡)
            cands = favorites.find_track(df, line.strip(), "", nk)
        status = "none" if not cands else "ok" if len(cands) == 1 else "ambiguous"
        results.append({"line": line.strip(), "status": status, "cands": cands})
    return results


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="'곡명 - 아티스트' 목록 파일")
    ap.add_argument("--apply", action="store_true", help="매칭된 곡을 data/favorites.json 에 저장")
    ap.add_argument("--data-dir", default=str(ROOT / "data"))
    args = ap.parse_args()

    data_dir = Path(args.data_dir)
    df = load_df(data_dir)
    lines = Path(args.file).read_text(encoding="utf-8").splitlines()
    results = match_lines(df, lines)
    marks = {"ok": "✔", "ambiguous": "?", "none": "✘"}
    for r in results:
        print(f"{marks[r['status']]} {r['line']}")
        for c in r["cands"][:5]:
            print(f"     → {c['artist']} - {c['name']} ({c['count']}회)")
    ok = [r for r in results if r["status"] == "ok"]
    print(f"\n매칭 {len(ok)}곡 / 애매함 {sum(r['status'] == 'ambiguous' for r in results)}곡 / 못 찾음 {sum(r['status'] == 'none' for r in results)}곡")
    if not args.apply:
        print("dry-run 입니다. 저장하려면 --apply 를 붙이세요.")
        return
    path = data_dir / favorites.FILE_NAME
    if path.exists():
        shutil.copy2(path, path.with_suffix(".json.bak"))
    added = 0
    for r in ok:
        c = r["cands"][0]
        added += favorites.set_favorite(path, df, c["artist"], c["name"], True)
    print(f"{added}곡을 저장했습니다 → {path}")


if __name__ == "__main__":
    main()
