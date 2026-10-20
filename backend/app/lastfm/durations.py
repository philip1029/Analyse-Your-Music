"""
곡 길이(초) 조회·캐시. 규칙 기반이라 AI 나 수동 작업 없이 누구의 데이터에서나 같은 순서로 동작한다.

조회 순서 (앞에서 찾으면 멈춘다)
  1. Apple 라이브러리 내보내기("Apple Music Library Tracks.json[.zip]"의 Track Duration)에서 아티스트+곡명이 같은 곡
     — 네트워크가 필요 없고 내 라이브러리의 실제 파일 길이라 가장 먼저 쓴다 (내보내기가 없으면 건너뜀)
  2. Last.fm track.getInfo (아티스트 + 곡명)
  3. 제목에서 길이를 바꾸지 않는 꼬리표((2011 Remaster), [Mono], (feat. X) 등)를 뗀 제목으로 다시 조회
     — Live·Remix·Edit 처럼 길이가 달라지는 꼬리표는 떼지 않는다
  4. Last.fm track.search 로 후보를 찾고, 제목이 같고 아티스트가 같거나 서로 포함될 때만 그 곡의 getInfo 사용
  5. Apple 내보내기에서 곡명만 같은 곡 (같은 곡명의 길이가 모두 같을 때만, 아티스트 표기가 달라 못 찾은 경우 보완)
  6. 못 찾으면 길이 없음(null)

캐시: data/track_durations.json — {"아티스트\t곡명"(정규화): {"sec", "src", "tried"}}.
일시적 실패(네트워크 오류·요청 한도)는 캐시하지 않고, 못 찾은 결과는 RETRY_UNKNOWN_DAYS 뒤에 다시 시도한다.
"""

import json
import os
import re
import tempfile
import time
import unicodedata
import zipfile
from collections import defaultdict
from pathlib import Path

import requests

LASTFM_URL = "http://ws.audioscrobbler.com/2.0/"
CACHE_NAME = "track_durations.json"
RETRY_UNKNOWN_DAYS = 30
REQUEST_GAP = 0.22
TRANSIENT_CODES = {8, 11, 16, 29}        # 일시적 오류 / 서비스 오류 / 요청 한도
NOT_FOUND_CODE = 6

# 길이를 바꾸지 않는 꼬리표만 뗀다 (Live, Remix, Edit, Version 은 길이가 달라지므로 제외)
_TAGS = r"(?:remaster(?:ed)?|mono|stereo|deluxe|anniversary|bonus|feat\.?|featuring|with)"
_SUFFIX_PAREN = re.compile(rf"\s*[\(\[（][^()\[\]（）]*?{_TAGS}[^()\[\]（）]*[\)\]）]\s*$", re.IGNORECASE)
_SUFFIX_DASH = re.compile(rf"\s+[-–—]\s+[^-–—]*?{_TAGS}[^-–—]*$", re.IGNORECASE)


def norm(s) -> str:
    """이름 비교용 정규화: NFKC, 소문자, 글자·숫자만 남김."""
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", str(s or "")).lower())


def cache_key(artist, track) -> str:
    return f"{norm(artist)}\t{norm(track)}"


def title_variants(track: str) -> list[str]:
    """[원래 제목, (있으면) 길이를 바꾸지 않는 꼬리표를 뗀 제목]."""
    stripped = track
    for _ in range(4):
        new = _SUFFIX_DASH.sub("", _SUFFIX_PAREN.sub("", stripped)).strip()
        if new == stripped:
            break
        stripped = new
    return [track] + ([stripped] if stripped and stripped != track else [])


# --------------------------------------------------------------------------- 캐시

def load_cache(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("tracks", {})
    except (OSError, ValueError):
        return {}


def save_cache(path, tracks: dict) -> None:
    p = Path(path)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "tracks": tracks}, f, ensure_ascii=False)
    os.replace(tmp, p)


def needs_lookup(entry, now=None, retry_days=RETRY_UNKNOWN_DAYS) -> bool:
    if entry is None:
        return True
    if entry.get("sec"):
        return False
    return (now or time.time()) - entry.get("tried", 0) > retry_days * 86400


# --------------------------------------------------------------------------- Apple 라이브러리

class AppleDurations:
    """Apple 라이브러리 내보내기의 Track Duration(ms)."""

    def __init__(self, tracks=()):
        self.by_pair: dict[tuple[str, str], int] = {}
        by_title: dict[str, set[int]] = defaultdict(set)
        for t in tracks:
            ms = t.get("Track Duration") or t.get("Total Time")
            title, artist = t.get("Title") or t.get("Name"), t.get("Artist")
            if not (title and ms):
                continue
            sec = round(int(ms) / 1000)
            self.by_pair.setdefault((norm(artist), norm(title)), sec)
            by_title[norm(title)].add(sec)
        # 곡명만으로 찾을 때는 길이가 모두 같은(±2초) 경우만 믿는다
        self.by_title = {t: sorted(s)[0] for t, s in by_title.items() if max(s) - min(s) <= 2}

    def get_pair(self, artist, track):
        return self.by_pair.get((norm(artist), norm(track)))

    def get_title(self, artist, track):
        return self.by_title.get(norm(track))


def load_apple_durations(apple_dir) -> AppleDurations | None:
    """폴더 안의 'Apple Music Library Tracks.json(.zip)' 을 읽는다. 없으면 None."""
    if not apple_dir:
        return None
    d = Path(apple_dir)
    try:
        zp, jp = d / "Apple Music Library Tracks.json.zip", d / "Apple Music Library Tracks.json"
        if zp.exists():
            with zipfile.ZipFile(zp) as z:
                name = next(n for n in z.namelist() if n.endswith(".json"))
                return AppleDurations(json.loads(z.read(name)))
        if jp.exists():
            return AppleDurations(json.loads(jp.read_text(encoding="utf-8")))
    except (OSError, ValueError, StopIteration, zipfile.BadZipFile):
        return None
    return None


# --------------------------------------------------------------------------- Last.fm

class LastFmClient:
    def __init__(self, api_key, gap=REQUEST_GAP):
        self.api_key, self.gap = api_key, gap
        self.calls = 0

    def _get(self, params):
        """(상태, JSON). 상태: ok / notfound / error(일시적)."""
        try:
            data = requests.get(LASTFM_URL, params={**params, "api_key": self.api_key, "format": "json"}, timeout=10).json()
        except Exception:
            return "error", None
        finally:
            self.calls += 1
            time.sleep(self.gap)
        err = data.get("error")
        if err in TRANSIENT_CODES:
            return "error", None
        if err:
            return "notfound", None
        return "ok", data

    def get_duration(self, artist, track):
        """(상태, 초). 길이가 없으면 초 = 0."""
        st, data = self._get({"method": "track.getInfo", "artist": artist, "track": track, "autocorrect": 1})
        if st != "ok":
            return st, 0
        return "ok", round(int(data.get("track", {}).get("duration", 0) or 0) / 1000)

    def search(self, artist, track):
        """track.search 후보 [(아티스트, 곡명)]."""
        st, data = self._get({"method": "track.search", "artist": artist, "track": track, "limit": 5})
        if st != "ok":
            return st, []
        hits = data.get("results", {}).get("trackmatches", {}).get("track", [])
        return "ok", [(h.get("artist", ""), h.get("name", "")) for h in hits]


def _artist_matches(want, got) -> bool:
    a, b = norm(want), norm(got)
    return bool(a) and bool(b) and (a == b or a in b or b in a)


def resolve_duration(artist, track, lastfm, apple=None, use_search=True) -> dict | None:
    """
    {"sec", "src"} (못 찾으면 sec = None) 또는, 일시적 오류 때문에 판단을 미뤄야 하면 None (캐시하지 않음).
    lastfm: get_duration / search 를 가진 객체 (테스트에서는 가짜 객체).
    """
    if apple is not None:
        sec = apple.get_pair(artist, track)
        if sec:
            return {"sec": sec, "src": "apple"}
    transient = False
    for i, title in enumerate(title_variants(track)):
        st, sec = lastfm.get_duration(artist, title)
        transient |= st == "error"
        if sec:
            return {"sec": sec, "src": "lastfm" if i == 0 else "lastfm:variant"}
    if use_search:
        st, hits = lastfm.search(artist, track)
        transient |= st == "error"
        for h_artist, h_title in hits:
            if norm(h_title) == norm(track) and _artist_matches(artist, h_artist):
                st, sec = lastfm.get_duration(h_artist, h_title)
                transient |= st == "error"
                if sec:
                    return {"sec": sec, "src": "lastfm:search"}
                break
    if apple is not None:
        sec = apple.get_title(artist, track)
        if sec:
            return {"sec": sec, "src": "apple:title"}
    return None if transient else {"sec": None, "src": None}


# --------------------------------------------------------------------------- 조회 (백엔드용)

class DurationLookup:
    """캐시 파일을 읽어 (아티스트, 곡명) -> 초. 파일이 바뀌면 다시 읽는다."""

    def __init__(self, path):
        self.path, self._mtime, self._tracks, self._by_title = Path(path), None, {}, {}

    def _refresh(self):
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            self._mtime, self._tracks, self._by_title = None, {}, {}
            return
        if mtime == self._mtime:
            return
        self._mtime, self._tracks = mtime, load_cache(self.path)
        by_title = defaultdict(set)
        for k, v in self._tracks.items():
            if v.get("sec"):
                by_title[k.split("\t", 1)[1]].add(v["sec"])
        self._by_title = {t: next(iter(s)) for t, s in by_title.items() if len(s) == 1}

    def get(self, artist, track) -> int | None:
        self._refresh()
        entry = self._tracks.get(cache_key(artist, track))
        if entry and entry.get("sec"):
            return entry["sec"]
        # 아티스트 표기가 달라 못 찾으면, 같은 곡명의 길이가 하나뿐일 때만 그 값을 쓴다
        return self._by_title.get(norm(track))
