"""
앨범 커버·아티스트 사진을 사용자가 직접 지정하는 기능의 저장소.

자동으로 못 찾은 커버를 사용자가 올린 이미지로 대신한다. 이미지는 data/covers/ 에 JPEG 로 저장하고,
어떤 항목이 어떤 파일을 쓰는지는 data/cover_overrides.json 에 기록한다. 자동 조회 결과보다 항상 우선한다.

  - 이미지는 base64 data URL 로 받는다 (브라우저가 올리기 전에 줄여서 보낸다). 별도 업로드 라이브러리가 필요 없다.
  - Pillow 로 실제로 열어 보고 JPEG/PNG/WEBP 만 받는다 (SVG 등은 거부). 긴 변 800px 로 줄여 JPEG 로 다시 저장한다.
  - 파일 이름은 이미지 내용의 해시라서, 사용자 입력이 경로에 들어가지 않는다.
"""

import base64
import binascii
import hashlib
import io
import json
import os
import re
import tempfile
import time
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.lastfm.durations import norm

ROOT = Path(__file__).resolve().parents[3]
COVERS_DIR = ROOT / "data" / "covers"
OVERRIDES_FILE = ROOT / "data" / "cover_overrides.json"

MAX_BYTES = 8 * 1024 * 1024            # 올릴 수 있는 이미지 크기 (디코드 후)
MAX_SIDE = 800                         # 저장할 때 긴 변 최대 픽셀
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP"}
KINDS = ("album", "artist")
_DATA_URL = re.compile(r"^data:image/(?:png|jpeg|jpg|webp);base64,(?P<b64>[A-Za-z0-9+/=\s]+)$")
_FILE_NAME = re.compile(r"^[0-9a-f]{40}\.jpg$")


def _key(kind: str, artist: str | None, album: str | None) -> str:
    if kind == "artist":
        return norm(artist)
    return f"{norm(artist)}\t{norm(album)}"


def _load() -> dict:
    try:
        data = json.loads(OVERRIDES_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    return {k: data.get(k, {}) for k in KINDS}


def _save(data: dict) -> None:
    OVERRIDES_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=OVERRIDES_FILE.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, OVERRIDES_FILE)


def decode_data_url(data_url: str) -> bytes:
    m = _DATA_URL.match((data_url or "").strip())
    if not m:
        raise ValueError("PNG/JPEG/WEBP 이미지만 올릴 수 있습니다.")
    try:
        data = base64.b64decode(re.sub(r"\s+", "", m.group("b64")), validate=True)
    except (binascii.Error, ValueError):
        raise ValueError("이미지 데이터가 올바르지 않습니다.")
    if len(data) > MAX_BYTES:
        raise ValueError("이미지가 너무 큽니다 (최대 8MB).")
    return data


def normalize_image(data: bytes) -> bytes:
    """실제로 열어 보고(형식 확인), 긴 변 MAX_SIDE 이하의 JPEG 바이트로 다시 만든다."""
    try:
        im = Image.open(io.BytesIO(data))
        if im.format not in ALLOWED_FORMATS:
            raise ValueError("PNG/JPEG/WEBP 이미지만 올릴 수 있습니다.")
        im.load()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError("이미지를 읽을 수 없습니다.")
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        im = bg
    else:
        im = im.convert("RGB")
    im.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    out = io.BytesIO()
    im.save(out, format="JPEG", quality=88, optimize=True, progressive=True)
    return out.getvalue()


def file_path(name: str) -> Path | None:
    """저장된 커버 파일 경로. 이름 형식이 맞고 파일이 있을 때만 (경로 조작 방지)."""
    if not _FILE_NAME.match(name or ""):
        return None
    p = COVERS_DIR / name
    return p if p.is_file() else None


def _url(name: str) -> str:
    return f"/api/cover-file/{name}"


def get_url(kind: str, artist: str | None, album: str | None = None) -> str | None:
    entry = _load().get(kind, {}).get(_key(kind, artist, album))
    if entry and file_path(entry.get("file", "")):
        return _url(entry["file"])
    return None


def _referenced(data: dict) -> set[str]:
    return {e.get("file") for kind in KINDS for e in data.get(kind, {}).values()}


def set_override(kind: str, artist: str | None, album: str | None, data_url: str) -> str:
    if kind not in KINDS:
        raise ValueError("kind 는 album 또는 artist 여야 합니다.")
    if not (artist or "").strip() or (kind == "album" and not (album or "").strip()):
        raise ValueError("아티스트와 앨범 이름이 필요합니다." if kind == "album" else "아티스트 이름이 필요합니다.")
    jpeg = normalize_image(decode_data_url(data_url))
    name = hashlib.sha1(jpeg).hexdigest() + ".jpg"
    COVERS_DIR.mkdir(parents=True, exist_ok=True)
    (COVERS_DIR / name).write_bytes(jpeg)
    data = _load()
    key = _key(kind, artist, album)
    old = data[kind].get(key, {}).get("file")
    data[kind][key] = {"file": name, "artist": artist, "album": album if kind == "album" else None, "set_at": int(time.time())}
    _save(data)
    if old and old != name and old not in _referenced(data):
        (COVERS_DIR / old).unlink(missing_ok=True)
    return _url(name)


def clear_override(kind: str, artist: str | None, album: str | None = None) -> bool:
    data = _load()
    entry = data.get(kind, {}).pop(_key(kind, artist, album), None)
    if not entry:
        return False
    _save(data)
    if entry.get("file") and entry["file"] not in _referenced(data):
        (COVERS_DIR / entry["file"]).unlink(missing_ok=True)
    return True


def count() -> int:
    return sum(len(v) for v in _load().values())
