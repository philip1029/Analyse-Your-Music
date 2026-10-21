"""
같은 앨범/곡인데 제목이 다르게 적힌 항목(예: Romance / 로맨스)을 아티스트 안에서 직접 합치는 기능의 데이터 처리.

규칙은 config/title_merge.txt 에 "곡|앨범 :: 아티스트 :: 변형 -> 통일 표기" 한 줄로 남고, scripts/normalize_titles.py 가
백업(.bak_titlenorm_*)과 변경 기록(data/title_normalize_log.csv)을 남기며 data CSV 에 반영한다. 새로고침 때도 같은 규칙이 적용된다.
통일 표기는 Last.fm 이 쓰는 표기(L 행이 더 많은 쪽)를 기본으로 권한다. 규칙 기반이라 AI 없이 같은 결과가 나온다.
"""

import csv
import shutil
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import preprocess as pp  # noqa: E402
from normalize_titles import LOG_FIELDS, load_manual_title_merges  # noqa: E402

KINDS = {"track": "곡", "album": "앨범"}


def titles_of(df: pd.DataFrame, artist: str, kind: str) -> list[dict]:
    """그 아티스트의 앨범/곡 표기별 행 수(A/L), 많이 들은 순."""
    rows = df[(df["artist"] == artist) & (df[kind] != "")]
    out = []
    for title, g in rows.groupby(kind):
        src = g["source"].value_counts()
        out.append({"title": title, "A": int(src.get("A", 0)), "L": int(src.get("L", 0)), "total": int(len(g))})
    return sorted(out, key=lambda x: (-x["total"], x["title"]))


def load_rules(path: Path) -> list[dict]:
    return [{"kind": f, "artist": a, "variant": v, "canonical": c} for (f, a, v), c in load_manual_title_merges(path).items()]


def preview(df: pd.DataFrame, kind: str, artist: str, variant: str, canonical: str, rules_path: Path) -> dict:
    variant, canonical = variant.strip(), canonical.strip()
    if kind not in KINDS:
        return {"error": "종류는 track 또는 album 이어야 해요."}
    items = {t["title"]: t for t in titles_of(df, artist, kind)}
    empty = {"title": "", "A": 0, "L": 0, "total": 0}
    v, c = items.get(variant, {**empty, "title": variant}), items.get(canonical, {**empty, "title": canonical})
    out = {"kind": kind, "artist": artist, "variant": v, "canonical": c, "suggest_swap": v["L"] > c["L"], "collisions": 0, "error": None}
    if not variant or not canonical:
        out["error"] = f"합칠 {KINDS[kind]} 두 개를 모두 고르세요."
    elif variant == canonical:
        out["error"] = f"서로 다른 {KINDS[kind]}을(를) 고르세요."
    elif v["total"] == 0 or c["total"] == 0:
        out["error"] = f"이 아티스트의 기록에 없는 {KINDS[kind]}이에요: {variant if v['total'] == 0 else canonical}"
    else:
        rules = {(r["kind"], r["artist"], r["variant"]): r["canonical"] for r in load_rules(rules_path)}
        if (kind, artist, variant) in rules:
            out["error"] = f"‘{variant}’ 는 이미 ‘{rules[(kind, artist, variant)]}’ 로 합치는 규칙이 있어요."
        elif (kind, artist, canonical) in rules:
            out["error"] = f"‘{canonical}’ 는 이미 ‘{rules[(kind, artist, canonical)]}’ 로 합치는 규칙이 있어서 통일 이름이 될 수 없어요."
        elif kind == "track":
            # 곡 제목을 바꾸면 같은 시각·같은 아티스트의 다른 곡명 행과 키(uts+artist+track)가 겹칠 수 있다
            a = df[(df["artist"] == artist) & (df["track"] == variant)]
            b = df[(df["artist"] == artist) & (df["track"] == canonical)]
            out["collisions"] = len(set(a["uts"].astype(str)) & set(b["uts"].astype(str)))
            if out["collisions"]:
                out["error"] = f"같은 시각의 기록이 {out['collisions']}건 겹쳐서 합칠 수 없어요. 먼저 새로고침의 전처리(중복 정리)로 겹침을 없애세요."
    return out


def _line(kind: str, artist: str, variant: str, canonical: str) -> str:
    return f"{kind} :: {artist} :: {variant} -> {canonical}"


def add_rule(path: Path, kind: str, artist: str, variant: str, canonical: str) -> str | None:
    before = path.read_text(encoding="utf-8") if path.exists() else None
    text = before if before is not None else "# 직접 합치는 곡/앨범 제목: 곡|앨범 :: 아티스트 :: 변형 -> 통일 표기 (한 줄에 하나)\n"
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + _line(kind, artist.strip(), variant.strip(), canonical.strip()) + "\n", encoding="utf-8")
    return before


def restore_rules(path: Path, before: str | None) -> None:
    if before is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(before, encoding="utf-8")


def _read_log(data_dir: Path) -> list[dict]:
    path = Path(data_dir) / "title_normalize_log.csv"
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _merged_keys(log: list[dict], kind: str, artist: str, variant: str, canonical: str) -> set[tuple[str, str, str, str]]:
    """변형 -> 통일로 바뀐 행 중 아직 되돌리지 않은 것의 (uts, source, 곡, 앨범 칸 값 대신 곡). 기록을 순서대로 읽어 되돌린 행은 뺀다."""
    keys: set[tuple[str, str, str, str]] = set()
    for r in log:
        if r.get("field") != kind or r.get("artist") != artist:
            continue
        # 곡 제목을 바꾼 행은 로그의 track 칸이 바뀌기 전/후 제목이라 달라지므로, 곡 종류는 uts+source 로만 맞춘다
        k = (r.get("uts", ""), r.get("source", ""), "" if kind == "track" else r.get("track", ""), "")
        if r.get("old_title") == variant and r.get("new_title") == canonical:
            keys.add(k)
        elif r.get("old_title") == canonical and r.get("new_title") == variant:
            keys.discard(k)
    return keys


def _row_key(r: dict, kind: str) -> tuple[str, str, str, str]:
    # 곡 제목을 바꾼 행은 로그의 track 칸이 바뀌기 전 제목이라, 되돌릴 때는 uts+source 로만 맞춘다
    return (r.get("uts", ""), r.get("source", ""), "" if kind == "track" else r.get("track", ""), "")


def restorable_rows(df: pd.DataFrame, data_dir: Path, kind: str, artist: str, variant: str, canonical: str) -> int:
    keys = {(u, s, "" if kind == "track" else t, "") for u, s, t, _ in _merged_keys(_read_log(data_dir), kind, artist, variant, canonical)}
    if not keys:
        return 0
    cur = df[(df["artist"] == artist) & (df[kind] == canonical)]
    return sum(1 for u, s, t in zip(cur["uts"].astype(str), cur["source"], cur["track"]) if (u, s, "" if kind == "track" else t, "") in keys)


def _drop_rule_lines(path: Path, kind: str, artist: str, variant: str) -> None:
    if not path.exists():
        return
    kept = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.strip().split(" :: ", 2)
        if len(parts) == 3 and not line.lstrip().startswith("#") and parts[0].strip() == kind and parts[1].strip() == artist and parts[2].split(" -> ", 1)[0].strip() == variant:
            continue
        kept.append(line)
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def undo_merge(data_dir: Path, rules_path: Path, kind: str, artist: str, variant: str, canonical: str) -> dict:
    """합치기를 되돌린다: 규칙을 지우고, 그때 제목이 바뀐 행만 원래 제목으로 복원한다(백업 .bak_titleundo_* 와 변경 기록 포함)."""
    if not any(r == {"kind": kind, "artist": artist, "variant": variant, "canonical": canonical} for r in load_rules(rules_path)):
        raise ValueError(f"‘{variant}’ → ‘{canonical}’ 합치기 규칙이 없어요.")
    _drop_rule_lines(rules_path, kind, artist, variant)
    base = {"restored_rows": 0, "backup": None, "kind": kind, "artist": artist, "variant": variant, "canonical": canonical}

    csv_path = pp.find_data_csv(data_dir)
    if not csv_path:
        return base
    log = _read_log(data_dir)
    keys = {(u, s, "" if kind == "track" else t, "") for u, s, t, _ in _merged_keys(log, kind, artist, variant, canonical)}
    header, rows = pp.read_csv(csv_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_log = []
    for r in rows:
        if r.get("artist") == artist and r.get(kind) == canonical and _row_key(r, kind) in keys:
            new_log.append({"uts": r.get("uts", ""), "utc_time": r.get("utc_time", ""), "artist": artist, "source": r.get("source", ""), "field": kind,
                            "old_title": canonical, "new_title": variant, "rule": "undo_merge", "changed_at": now, "track": r.get("track", "")})
            r[kind] = variant
    if not new_log:
        return base

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = csv_path.with_name(csv_path.name + f".bak_titleundo_{stamp}")
    shutil.copy2(csv_path, backup)
    pp.write_csv_atomic(csv_path, header, rows)
    pp.write_csv_atomic(Path(data_dir) / "title_normalize_log.csv", LOG_FIELDS, log + new_log)
    return {**base, "restored_rows": len(new_log), "backup": backup.name}
