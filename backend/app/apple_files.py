"""
Apple Music 데이터 폴더 안내: 앱이 읽는 파일마다 "무엇에 쓰이는지 / 어디서 받는지 / 지금 폴더에 있는지"를 알려 주고,
다른 위치에 받아 둔 파일을 설정한 Apple 폴더로 가져온다(복사). 파일이 없어도 앱은 Last.fm 데이터만으로 동작하고 해당 기능만 건너뛴다.
"""

import json
import shutil
import zipfile
from pathlib import Path

PRIVACY = "privacy.apple.com → ‘데이터 사본 요청’ → ‘Apple Music 활동’ 내보내기 안에 들어 있어요"
MUSIC_APP = "음악 앱(맥) → 파일 → 라이브러리 → "

FILE_INFO = [
    {
        "key": "play_activity",
        "label": "재생 로그",
        "names": ["Apple Music Play Activity.csv"],
        "purpose": "가짜/중복 스크로블 판정에 쓰는 Apple 재생 기록",
        "source": PRIVACY,
    },
    {
        "key": "library_tracks",
        "label": "보관함 곡 목록",
        "names": ["Apple Music Library Tracks.json.zip", "Apple Music Library Tracks.json"],
        "purpose": "정확한 곡 길이 (청취 시간 계산에 쓰는 곡 길이의 1순위)",
        "source": PRIVACY + " (압축 파일 그대로 두면 돼요)",
    },
    {
        "key": "daily_tracks",
        "label": "일별 곡 목록",
        "names": ["Apple Music - Play History Daily Tracks.csv"],
        "purpose": "아티스트가 빈 기록 채우기",
        "source": PRIVACY,
    },
    {
        "key": "library_xml",
        "label": "보관함 XML (선택)",
        "names": ["전체.xml"],
        "purpose": "곡 길이·아티스트 보강",
        "source": MUSIC_APP + "‘라이브러리 내보내기…’ 로 만들고, 파일 이름을 ‘전체.xml’ 로 저장하세요",
    },
    {
        "key": "playlist_xml",
        "label": "플레이리스트 XML (선택)",
        "names": ["플레이리스트.xml"],
        "purpose": "Apple 세션 재구성 스크립트(build_apple_sessions.py)에서 아티스트 보강",
        "source": MUSIC_APP + "‘플레이리스트 내보내기…’ 로 만들고, 파일 이름을 ‘플레이리스트.xml’ 로 저장하세요",
    },
    {
        "key": "container_details",
        "label": "앨범 정보 (선택)",
        "names": ["Apple Music - Container Details.csv"],
        "purpose": "Apple 세션 재구성 스크립트에서 앨범 → 아티스트 연결",
        "source": PRIVACY,
    },
]
BY_KEY = {f["key"]: f for f in FILE_INFO}


def checklist(folder: str | None) -> dict:
    """설정된 Apple 폴더 기준으로 파일별 상태. 폴더가 없으면 files 의 found 는 모두 False."""
    base = Path(folder) if folder else None
    ok = bool(base and base.is_dir())
    files = []
    for info in FILE_INFO:
        found = next((n for n in info["names"] if ok and (base / n).exists()), None)
        size = (base / found).stat().st_size if found else None
        files.append({**{k: info[k] for k in ("key", "label", "names", "purpose", "source")}, "found": found, "size": size})
    return {"folder": str(base) if ok else "", "files": files}


def _find_in(src: Path, names: list[str]) -> Path | None:
    """폴더를 줬을 때 그 안(두 단계까지)에서 파일을 찾는다."""
    level = [src]
    for _ in range(3):
        for d in level:
            for n in names:
                if (d / n).is_file():
                    return d / n
        try:
            level = [c for d in level for c in sorted(p for p in d.iterdir() if p.is_dir())]
        except OSError:
            return None
    return None


def _sane(path: Path, dest_name: str) -> str | None:
    """겉모양만 확인한다 (엉뚱한 파일을 이름만 바꿔 넣는 실수를 막는 정도). 문제가 있으면 사유를 돌려준다."""
    try:
        if path.stat().st_size == 0:
            return "빈 파일이에요."
        if dest_name.endswith(".zip"):
            return None if zipfile.is_zipfile(path) else "zip 압축 파일이 아니에요."
        if dest_name.endswith(".json"):
            json.loads(path.read_text(encoding="utf-8")[:2_000_000] if path.stat().st_size < 2_000_000 else "{}")
            return None
        head = path.read_bytes()[:400].decode("utf-8-sig", errors="ignore")
        if dest_name.endswith(".xml"):
            return None if "<?xml" in head or "<plist" in head else "XML 파일이 아니에요."
        if dest_name.endswith(".csv"):
            return None if "," in head.splitlines()[0] else "CSV 파일이 아니에요."
    except (OSError, ValueError, IndexError):
        return "파일을 읽지 못했어요."
    return None


def import_file(folder: str | None, source: str, key: str, overwrite: bool = False) -> dict:
    """다른 위치에 받아 둔 파일(또는 그 파일이 든 폴더)을 Apple 폴더로 복사한다. 원본은 그대로 둔다."""
    info = BY_KEY.get(key)
    if info is None:
        raise ValueError("알 수 없는 파일 종류예요.")
    base = Path(folder) if folder else None
    if not base or not base.is_dir():
        raise ValueError("먼저 위에서 Apple Music 폴더를 저장하세요.")
    src = Path(source.strip()).expanduser()
    if src.is_dir():
        found = _find_in(src, info["names"])
        if found is None:
            raise ValueError(f"그 폴더에서 {' 또는 '.join(info['names'])} 를 찾지 못했어요.")
        src = found
    if not src.is_file():
        raise ValueError("그 경로에 파일이 없어요.")
    # 도착 이름: 원래 이름이 표준 이름이면 그대로, 아니면 확장자가 맞는 표준 이름(없으면 첫 번째 이름)
    dest_name = next((n for n in info["names"] if n == src.name), None) or next((n for n in info["names"] if src.name.lower().endswith(Path(n).suffix.lower())), None)
    if dest_name is None:
        raise ValueError(f"이 종류의 파일 형식이 아니에요 ({' / '.join(Path(n).suffix for n in info['names'])}).")
    dest = base / dest_name
    if src.resolve() == dest.resolve():
        raise ValueError("이미 그 위치에 있는 파일이에요.")
    problem = _sane(src, dest_name)
    if problem:
        raise ValueError(f"{src.name}: {problem}")
    if dest.exists() and not overwrite:
        raise FileExistsError(f"{dest_name} 가 이미 있어요. 덮어쓰려면 다시 확인해 주세요.")
    shutil.copy2(src, dest)
    return {"copied": dest_name, "size": dest.stat().st_size}
