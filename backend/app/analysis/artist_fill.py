"""
빈 artist 행을 사용자가 직접 채우는 기능의 데이터 처리.

  - missing_groups: artist 가 빈 행을 (곡, 앨범) 묶음으로 보여 주고, 같은 앨범/같은 곡에서 이미 알려진 아티스트를 후보로 준다.
  - resolve_artist: 입력한 아티스트가 라이브러리에 이미 있는 아티스트(대소문자·띄어쓰기·기호만 다른 표기)면 기존 표기로 합친다.
  - apply_assignments: 백업(.bak_artistfill_*)을 만들고 CSV 를 고친 뒤 data/artist_fill_log.csv 에 행마다 기록한다.
규칙 기반이라 AI 없이 같은 결과가 나온다. source 열은 바꾸지 않는다.
"""

import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from app.analysis.keys import name_key

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import preprocess as pp  # noqa: E402  (read_csv / write_csv_atomic 재사용)
from csv_backup import make_backup  # noqa: E402
from fill_missing_artists import LOG_FIELDS  # noqa: E402


def missing_groups(df: pd.DataFrame, limit: int = 200) -> dict:
    """artist 가 빈 행을 (곡, 앨범)으로 묶어 많이 들은 순으로 돌려준다. 항목마다 후보 아티스트(근거 포함)가 따라간다."""
    d = df.fillna("")
    empty = d[d["artist"].astype(str).str.strip() == ""]
    if empty.empty:
        return {"total_rows": 0, "total_groups": 0, "items": []}

    filled = d[d["artist"].astype(str).str.strip() != ""]
    by_album: dict[str, Counter] = defaultdict(Counter)
    for (album, artist), n in filled[filled["album"] != ""].groupby(["album", "artist"]).size().items():
        by_album[album][artist] += int(n)
    by_track: dict[str, Counter] = defaultdict(Counter)
    tkey = {t: name_key(t) for t in pd.unique(filled["track"])}
    for (t, artist), n in filled.assign(_k=filled["track"].map(tkey)).groupby(["_k", "artist"]).size().items():
        by_track[t][artist] += int(n)

    groups = empty.groupby(["track", "album"]).agg(count=("track", "size"), first=("utc_time", "min"), last=("utc_time", "max")).reset_index()
    groups = groups.sort_values(["count", "track"], ascending=[False, True], kind="stable")

    items = []
    for _, g in groups.head(limit).iterrows():
        sug: dict[str, dict] = {}
        for artist, n in by_album.get(g["album"], Counter()).items():
            sug.setdefault(artist, {"artist": artist, "reasons": [], "count": 0})["reasons"].append("같은 앨범")
            sug[artist]["count"] += n
        for artist, n in by_track.get(name_key(g["track"]), Counter()).items():
            s = sug.setdefault(artist, {"artist": artist, "reasons": [], "count": 0})
            s["reasons"].append("같은 곡")
            s["count"] += n
        ranked = sorted(sug.values(), key=lambda s: (-len(s["reasons"]), -s["count"], s["artist"]))[:4]
        items.append({"track": g["track"], "album": g["album"], "count": int(g["count"]), "first": g["first"], "last": g["last"], "suggestions": ranked})
    return {"total_rows": int(len(empty)), "total_groups": int(len(groups)), "items": items}


def resolve_artist(artist_counts: Counter, typed: str) -> tuple[str, bool]:
    """입력한 이름을 라이브러리의 기존 아티스트 표기에 맞춘다. 반환: (사용할 이름, 기존 아티스트로 합쳤는지)."""
    t = typed.strip()
    if not t:
        raise ValueError("아티스트 이름이 비어 있습니다.")
    canon: dict[str, str] = {}
    for name, _ in artist_counts.most_common():     # 가장 많이 쓰인 표기가 대표 표기
        canon.setdefault(name_key(name), name)
    existing = canon.get(name_key(t))
    if existing is None:
        return t, False
    return existing, existing != t


def apply_assignments(data_dir: Path, assignments: list[dict]) -> dict:
    """assignments: [{"track", "album", "artist"}]. artist 가 빈 행 중 곡·앨범이 같은 행만 채운다. 백업과 변경 기록을 남긴다."""
    import csv

    csv_path = pp.find_data_csv(data_dir)
    if not csv_path:
        raise ValueError("data 폴더에 *_scrobbles.csv 가 없습니다.")
    header, rows = pp.read_csv(csv_path)
    counts = Counter((r.get("artist") or "").strip() for r in rows if (r.get("artist") or "").strip())

    target: dict[tuple[str, str], tuple[str, bool]] = {}
    for a in assignments:
        typed = (a.get("artist") or "").strip()
        if not typed:
            continue
        target[(a.get("track") or "", (a.get("album") or ""))] = resolve_artist(counts, typed)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    changed: dict[tuple[str, str], int] = defaultdict(int)
    log_rows = []
    for r in rows:
        if (r.get("artist") or "").strip():
            continue
        key = (r.get("track") or "", r.get("album") or "")
        if key not in target:
            continue
        name, merged = target[key]
        log_rows.append({
            "uts": r.get("uts", ""), "utc_time": r.get("utc_time", ""), "track": r.get("track", ""),
            "old_artist": r.get("artist", ""), "new_artist": name, "old_album": r.get("album", ""), "new_album": "",
            "rule": "manual:ui:merged" if merged else "manual:ui", "filled_at": now,
        })
        r["artist"] = name
        changed[key] += 1

    if not log_rows:
        return {"applied_rows": 0, "backup": None, "details": []}

    backup = make_backup(csv_path, "artistfill")
    log_path = Path(data_dir) / "artist_fill_log.csv"
    old_log = []
    if log_path.exists():
        with open(log_path, newline="", encoding="utf-8-sig") as f:
            old_log = list(csv.DictReader(f))
    pp.write_csv_atomic(csv_path, header, rows)
    pp.write_csv_atomic(log_path, LOG_FIELDS, old_log + log_rows)
    details = [{"track": t, "album": al, "artist": target[(t, al)][0], "merged": target[(t, al)][1], "rows": n} for (t, al), n in changed.items()]
    return {"applied_rows": len(log_rows), "backup": backup.name, "details": details}
