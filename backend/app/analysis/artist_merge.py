"""
같은 사람인데 이름이 다른 아티스트(예: 검정치마 / The Black Skirts)를 직접 합치는 기능의 데이터 처리.

합치는 규칙은 config/artist_merge.txt 에 "변형 -> 통일 이름" 한 줄로 남고, scripts/normalize_artists.py 가
백업(.bak_artistnorm_*)과 변경 기록(data/artist_normalize_log.csv)을 남기며 data CSV 에 반영한다.
통일 이름은 Last.fm 이 쓰는 표기(L 행이 더 많은 쪽)를 기본으로 권한다. 규칙 기반이라 AI 없이 같은 결과가 나온다.
"""

import csv
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

SCRIPTS_DIR = Path(__file__).resolve().parent.parent.parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
import preprocess as pp  # noqa: E402  (read_csv / write_csv_atomic 재사용)
from csv_backup import make_backup  # noqa: E402
from normalize_artists import LOG_FIELDS  # noqa: E402


def _stats(df: pd.DataFrame, name: str) -> dict:
    rows = df[df["artist"] == name]
    src = rows["source"].value_counts()
    return {"name": name, "A": int(src.get("A", 0)), "L": int(src.get("L", 0)), "total": int(len(rows))}


def load_rules(path: Path) -> dict[str, str]:
    rules: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "->" in line:
                v, c = line.split("->", 1)
                if v.strip() and c.strip() and v.strip() != c.strip():
                    rules[v.strip()] = c.strip()
    return rules


def preview(df: pd.DataFrame, variant: str, canonical: str, rules_path: Path) -> dict:
    """합치기 전 확인: 두 이름의 행 수(A/L), 권하는 통일 이름, 막아야 하는 문제(error)."""
    variant, canonical = variant.strip(), canonical.strip()
    v, c = _stats(df, variant), _stats(df, canonical)
    out = {"variant": v, "canonical": c, "suggest_swap": False, "collisions": 0, "error": None}

    if not variant or not canonical:
        out["error"] = "합칠 아티스트 두 명을 모두 고르세요."
    elif variant == canonical:
        out["error"] = "서로 다른 아티스트를 고르세요."
    elif v["total"] == 0 or c["total"] == 0:
        out["error"] = f"기록에 없는 아티스트예요: {variant if v['total'] == 0 else canonical}"
    else:
        rules = load_rules(rules_path)
        if variant in rules:
            out["error"] = f"‘{variant}’ 는 이미 ‘{rules[variant]}’ 로 합치는 규칙이 있어요."
        elif canonical in rules:
            out["error"] = f"‘{canonical}’ 는 이미 ‘{rules[canonical]}’ 로 합치는 규칙이 있어서 통일 이름이 될 수 없어요. ‘{rules[canonical]}’ 를 고르세요."
        # 이름을 바꾸면 같은 초·같은 곡이 겹치는 행(uts+artist+track 중복)이 있는지
        vr = df[df["artist"] == variant]
        cr = df[df["artist"] == canonical]
        out["collisions"] = len(set(zip(vr["uts"].astype(str), vr["track"])) & set(zip(cr["uts"].astype(str), cr["track"])))
        if out["collisions"] and not out["error"]:
            out["error"] = f"같은 시각·같은 곡 기록이 {out['collisions']}건 겹쳐서 합칠 수 없어요. 먼저 새로고침의 전처리(중복 정리)로 겹침을 없애세요."
    # Last.fm 이 쓰는 표기(L 행이 많은 쪽)를 통일 이름으로 권한다
    out["suggest_swap"] = v["L"] > c["L"]
    return out


def add_rule(path: Path, variant: str, canonical: str) -> str | None:
    """규칙 한 줄을 덧붙이고 이전 파일 내용을 돌려준다 (반영이 실패하면 되돌리는 데 쓴다)."""
    before = path.read_text(encoding="utf-8") if path.exists() else None
    text = before if before is not None else "# 직접 합치는 아티스트: 변형 -> 통일 이름 (한 줄에 하나)\n"
    if text and not text.endswith("\n"):
        text += "\n"
    path.write_text(text + f"{variant.strip()} -> {canonical.strip()}\n", encoding="utf-8")
    return before


def restore_rules(path: Path, before: str | None) -> None:
    if before is None:
        path.unlink(missing_ok=True)
    else:
        path.write_text(before, encoding="utf-8")


def _read_log(data_dir: Path) -> list[dict]:
    path = Path(data_dir) / "artist_normalize_log.csv"
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _merged_keys(log: list[dict], variant: str, canonical: str) -> set[tuple[str, str, str]]:
    """변형 -> 통일 이름으로 바뀐 행 중 아직 되돌리지 않은 것의 (uts, 곡, source). 기록을 순서대로 읽어 되돌린 행은 뺀다."""
    keys: set[tuple[str, str, str]] = set()
    for r in log:
        k = (r.get("uts", ""), r.get("track", ""), r.get("source", ""))
        if r.get("old_artist") == variant and r.get("new_artist") == canonical:
            keys.add(k)
        elif r.get("old_artist") == canonical and r.get("new_artist") == variant:
            keys.discard(k)
    return keys


def restorable_rows(df: pd.DataFrame, data_dir: Path, variant: str, canonical: str) -> int:
    """되돌리면 원래 이름(variant)으로 돌아갈 행 수 (아직 통일 이름으로 남아 있는 행만)."""
    keys = _merged_keys(_read_log(data_dir), variant, canonical)
    if not keys:
        return 0
    cur = df[df["artist"] == canonical]
    return sum(1 for k in zip(cur["uts"].astype(str), cur["track"], cur["source"]) if k in keys)


def _drop_rule_lines(path: Path, variant: str) -> None:
    if not path.exists():
        return
    kept = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if "->" in line and not line.lstrip().startswith("#") and line.split("->", 1)[0].strip() == variant:
            continue
        kept.append(line)
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def undo_merge(data_dir: Path, rules_path: Path, canonical_path: Path, variant: str, canonical: str) -> dict:
    """합치기를 되돌린다: 규칙을 지우고, 그때 이름이 바뀐 행을 원래 이름으로 복원한다(백업 .bak_artistundo_* 와 변경 기록 포함)."""
    if load_rules(rules_path).get(variant) != canonical:
        raise ValueError(f"‘{variant}’ → ‘{canonical}’ 합치기 규칙이 없어요.")
    _drop_rule_lines(rules_path, variant)          # 규칙을 먼저 지워야 이후 새로고침에서 다시 합쳐지지 않는다
    _drop_rule_lines(canonical_path, variant)

    csv_path = pp.find_data_csv(data_dir)
    if not csv_path:
        return {"restored_rows": 0, "backup": None, "variant": variant, "canonical": canonical}
    keys = _merged_keys(_read_log(data_dir), variant, canonical)
    header, rows = pp.read_csv(csv_path)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_rows = []
    for r in rows:
        if r.get("artist") == canonical and (r.get("uts", ""), r.get("track", ""), r.get("source", "")) in keys:
            log_rows.append({"uts": r.get("uts", ""), "utc_time": r.get("utc_time", ""), "track": r.get("track", ""), "source": r.get("source", ""),
                             "old_artist": canonical, "new_artist": variant, "rule": "undo_merge", "changed_at": now})
            r["artist"] = variant
    if not log_rows:
        return {"restored_rows": 0, "backup": None, "variant": variant, "canonical": canonical}

    backup = make_backup(csv_path, "artistundo")
    pp.write_csv_atomic(csv_path, header, rows)
    pp.write_csv_atomic(Path(data_dir) / "artist_normalize_log.csv", LOG_FIELDS, _read_log(data_dir) + log_rows)
    return {"restored_rows": len(log_rows), "backup": backup.name, "variant": variant, "canonical": canonical}
