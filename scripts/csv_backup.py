#!/usr/bin/env python3
"""스크로블 CSV 백업 (gzip 압축 + 종류별 보관 개수 제한). 데이터를 고치는 모든 스크립트가 이 모듈로 백업한다.

  - make_backup(csv_path, kind): `<csv>.bak_<kind>_<시각>.gz` 를 만들고, 같은 kind 의 오래된 .gz 백업을 정리한다.
    보관 개수는 환경변수 BACKUP_KEEP (기본 5). 압축하면 CSV 한 개가 4분의 1 정도로 줄어든다.
  - 정리/복원 CLI (기본은 dry-run):
        python3 scripts/csv_backup.py list                       # 백업 목록
        python3 scripts/csv_backup.py clean [--apply]            # 옛 압축 안 된 백업 정리: 종류별 최근 N개만 압축해 남기고 지움
        python3 scripts/csv_backup.py restore 파일이름 [--apply]  # 그 백업으로 CSV 를 되돌림 (되돌리기 전 현재 CSV 도 백업)
"""

import argparse
import gzip
import os
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_KEEP = 5
_NAME = re.compile(r"\.bak_(?P<kind>[A-Za-z0-9]+)_(?P<stamp>\d{8}_\d{6})(?P<gz>\.gz)?$")


def keep_count() -> int:
    try:
        return max(1, int(os.environ.get("BACKUP_KEEP", DEFAULT_KEEP)))
    except ValueError:
        return DEFAULT_KEEP


def _compress(src: Path, dest: Path) -> None:
    tmp = dest.with_name(dest.name + ".tmp")
    with open(src, "rb") as fin, gzip.open(tmp, "wb", compresslevel=6) as fout:
        shutil.copyfileobj(fin, fout)
    tmp.replace(dest)


def list_backups(csv_path: Path, kind: str | None = None) -> list[Path]:
    """csv_path 의 백업을 오래된 것부터 정렬해 돌려준다 (압축/비압축 모두)."""
    found = []
    for p in csv_path.parent.glob(csv_path.name + ".bak_*"):
        m = _NAME.search(p.name)
        if m and (kind is None or m.group("kind") == kind):
            found.append(p)
    return sorted(found, key=lambda p: _NAME.search(p.name).group("stamp"))


def make_backup(csv_path: Path, kind: str) -> Path:
    """CSV 를 압축해 백업하고, 같은 종류의 오래된 압축 백업은 BACKUP_KEEP 개만 남기고 지운다.
    압축 안 된 옛 백업은 여기서 건드리지 않는다 (clean 으로 확인 후 정리)."""
    csv_path = Path(csv_path)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup = csv_path.with_name(f"{csv_path.name}.bak_{kind}_{stamp}.gz")
    _compress(csv_path, backup)
    mine = [p for p in list_backups(csv_path, kind) if p.suffix == ".gz"]
    for old in mine[:-keep_count()]:
        old.unlink()
    return backup


def read_backup(path: Path) -> bytes:
    path = Path(path)
    if path.suffix == ".gz":
        with gzip.open(path, "rb") as f:
            return f.read()
    return path.read_bytes()


def restore_backup(csv_path: Path, backup: Path) -> Path:
    """backup 내용으로 csv_path 를 되돌린다. 되돌리기 전 현재 CSV 는 'prerestore' 백업으로 남긴다."""
    csv_path, backup = Path(csv_path), Path(backup)
    safety = make_backup(csv_path, "prerestore")
    tmp = csv_path.with_name(csv_path.name + ".restoring")
    tmp.write_bytes(read_backup(backup))
    tmp.replace(csv_path)
    return safety


def plan_clean(csv_path: Path) -> dict:
    """종류별로 최근 N개를 남기고 나머지는 지울 계획. 남기는 것 중 압축 안 된 것은 압축 대상."""
    keep = keep_count()
    by_kind: dict[str, list[Path]] = {}
    for p in list_backups(csv_path):
        by_kind.setdefault(_NAME.search(p.name).group("kind"), []).append(p)
    delete, compress = [], []
    for paths in by_kind.values():
        delete += paths[:-keep]
        compress += [p for p in paths[-keep:] if p.suffix != ".gz"]
    return {"delete": delete, "compress": compress}


def apply_clean(plan: dict) -> None:
    for p in plan["compress"]:
        _compress(p, p.with_name(p.name + ".gz"))
        p.unlink()
    for p in plan["delete"]:
        p.unlink()


def _size(paths) -> float:
    return sum(p.stat().st_size for p in paths) / 1e6


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["list", "clean", "restore"])
    parser.add_argument("name", nargs="?", help="restore 할 백업 파일 이름")
    parser.add_argument("--apply", action="store_true", help="실제로 반영 (기본은 dry-run)")
    args = parser.parse_args()

    sys.path.insert(0, str(SCRIPT_DIR))
    import preprocess as pp  # noqa: E402  (find_data_csv 재사용)

    csv_path = pp.find_data_csv(SCRIPT_DIR.parent / "data")
    if not csv_path:
        sys.exit("data 폴더에서 스크로블 CSV 를 찾지 못했어요.")

    if args.action == "list":
        for p in list_backups(csv_path):
            print(f"{p.stat().st_size / 1e6:6.2f}MB  {p.name}")
        return

    if args.action == "clean":
        plan = plan_clean(csv_path)
        print(f"종류별 최근 {keep_count()}개만 남깁니다.")
        print(f"  지울 백업 {len(plan['delete'])}개 ({_size(plan['delete']):.1f}MB)")
        for p in plan["delete"]:
            print(f"    - {p.name}")
        print(f"  압축할 백업 {len(plan['compress'])}개 ({_size(plan['compress']):.1f}MB → 약 {_size(plan['compress']) / 4:.1f}MB)")
        if args.apply:
            apply_clean(plan)
            print("정리했어요.")
        else:
            print("(dry-run) 실제로 정리하려면 --apply 를 붙이세요.")
        return

    if not args.name:
        sys.exit("restore 할 백업 파일 이름을 적어 주세요. (list 로 확인)")
    backup = csv_path.parent / args.name
    if not backup.exists() or not _NAME.search(backup.name):
        sys.exit(f"백업 파일을 찾지 못했어요: {args.name}")
    if not args.apply:
        print(f"{backup.name} 로 {csv_path.name} 을 되돌립니다. (dry-run) 실제로 하려면 --apply 를 붙이세요.")
        return
    safety = restore_backup(csv_path, backup)
    print(f"되돌렸어요. 되돌리기 전 CSV 는 {safety.name} 로 남겼어요.")


if __name__ == "__main__":
    main()
