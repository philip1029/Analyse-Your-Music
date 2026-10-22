"""
앨범 발매연도 조회·캐시 (Music by decade 의 바탕). 규칙 기반이라 AI 없이 누구의 데이터에서나 같은 순서로 동작한다.

연도 결정 순서 (앞에서 정해지면 멈춘다)
  0. 수동 보정 config/album_years.txt ("아티스트 :: 앨범 -> 연도") — 항상 최우선, 읽을 때 바로 적용되어 조회가 필요 없다
  1. MusicBrainz release-group 검색: 앨범 제목이 같고 아티스트가 같거나 서로 포함되는 항목의 최초 발매일(재발매·리마스터가 아닌 원래 연도)
     - (2011 Remaster), (2022 Mix), (Deluxe Edition), - EP 같은 꼬리표를 뗀 제목으로도 다시 찾는다
     - 후보 연도가 둘 이상(같은 제목의 다른 앨범, 예: 셀프 타이틀)이면 Apple 연도가 그 안에 있을 때 그것을 쓰고,
       없으면 가장 이른 연도를 쓰되 "ambiguous" 로 표시해 둔다
  2. Apple 라이브러리 내보내기("Apple Music Library Tracks.json[.zip]"의 Track Year) — MusicBrainz 에 없을 때만 보충 (내보내기가 없으면 건너뜀)
  3. 못 찾으면 연도 없음(null)

캐시: data/album_years.json — {"아티스트\t앨범"(정규화): {"year", "src", "tried", ["ambiguous", "retry"]}}.
일시적 실패(네트워크 오류·503)는 캐시하지 않고, MusicBrainz 만 못 닿았는데 Apple 이 답을 줬으면 그 값을 쓰되 "retry" 로 남겨 다음에 다시 확인한다.
못 찾은 결과는 RETRY_UNKNOWN_DAYS 뒤에 다시 시도한다. MusicBrainz 는 초당 1회 제한이 있어 한 번에 조회하는 개수를 limit 으로 나눠서 실행한다.
"""

import json
import os
import re
import tempfile
import threading
import time
import unicodedata
import zipfile
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import requests

from app.lastfm.durations import norm

ROOT = Path(__file__).resolve().parent.parent.parent
MB_URL = "https://musicbrainz.org/ws/2/release-group/"
USER_AGENT = "AnalyseYourMusic/0.2 (personal project; https://github.com/philip1029/Analyse-Your-Music)"
CACHE_NAME = "album_years.json"
OVERRIDES_PATH = ROOT / "config" / "album_years.txt"
RETRY_UNKNOWN_DAYS = 30
REQUEST_GAP = 1.1            # MusicBrainz 는 평균 초당 1회까지
SEARCH_LIMIT = 10
MIN_YEAR = 1900
MAX_TRANSIENT_RUN = 3        # 일시적 오류가 이만큼 연달아 나면 이번 조회를 멈춘다

fill_lock = threading.Lock()  # 같은 캐시 파일을 두 곳에서 동시에 채우지 않게 한다 (API 와 스크립트가 따로 돌 때는 호출하는 쪽이 책임)

# 원래 앨범 연도를 바꾸지 않는 꼬리표: 리마스터·믹스·에디션 등. (Live 는 다른 음반이므로 떼지 않는다)
_TAGS = r"(?:remaster(?:ed)?|mix(?:es)?|edition|deluxe|anniversary|expanded|reissue|bonus|mono|stereo)"
_PAREN = re.compile(rf"\s*[\(\[（][^()\[\]（）]*?{_TAGS}[^()\[\]（）]*[\)\]）]", re.IGNORECASE)
_DASH = re.compile(rf"\s+[-–—]\s+[^-–—]*?{_TAGS}[^-–—]*$", re.IGNORECASE)
_FORMAT_SUFFIX = re.compile(r"\s+[-–—]\s+(?:EP|Single)\s*$", re.IGNORECASE)


def cache_key(artist, album) -> str:
    return f"{norm(artist)}\t{norm(album)}"


def album_variants(album: str) -> list[str]:
    """[원래 제목, (있으면) 리마스터·믹스·에디션·- EP 꼬리표를 뗀 제목]."""
    stripped = album
    for _ in range(4):
        new = _FORMAT_SUFFIX.sub("", _DASH.sub("", _PAREN.sub("", stripped))).strip()
        if new == stripped:
            break
        stripped = new
    return [album] + ([stripped] if stripped and stripped != album else [])


def valid_year(value) -> int | None:
    try:
        y = int(str(value)[:4])
    except (TypeError, ValueError):
        return None
    return y if MIN_YEAR <= y <= date.today().year + 1 else None


# --------------------------------------------------------------------------- 수동 보정

def load_overrides(path=OVERRIDES_PATH) -> dict[tuple[str, str], int]:
    """config/album_years.txt: '아티스트 :: 앨범 -> 연도' (# 로 시작하는 줄과 빈 줄은 무시, 아티스트가 *이면 앨범 이름만으로 맞춤).
    형식이 틀린 줄은 건너뛴다."""
    p = Path(path)
    out: dict[tuple[str, str], int] = {}
    if not p.exists():
        return out
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "->" not in line or "::" not in line:
            continue
        left, year = line.rsplit("->", 1)
        artist, album = left.split("::", 1)
        y = valid_year(year.strip())
        if y and album.strip():
            a = "" if artist.strip() == "*" else norm(artist)
            out[(a, norm(album))] = y
    return out


def override_for(overrides, artist, album) -> int | None:
    return overrides.get((norm(artist), norm(album))) or overrides.get(("", norm(album)))


# --------------------------------------------------------------------------- 캐시

def load_cache(path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("albums", {})
    except (OSError, ValueError):
        return {}


def save_cache(path, albums: dict) -> None:
    p = Path(path)
    fd, tmp = tempfile.mkstemp(dir=p.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"version": 1, "albums": albums}, f, ensure_ascii=False)
    os.replace(tmp, p)


def needs_lookup(entry, now=None, retry_days=RETRY_UNKNOWN_DAYS) -> bool:
    if entry is None:
        return True
    if entry.get("retry"):
        return True
    if entry.get("year"):
        return False
    return (now or time.time()) - entry.get("tried", 0) > retry_days * 86400


# --------------------------------------------------------------------------- Apple 라이브러리

class AppleYears:
    """Apple 라이브러리 내보내기의 Track Year(없으면 Release Date 의 연도)."""

    def __init__(self, tracks=()):
        by_pair: dict[tuple[str, str], list[int]] = defaultdict(list)
        by_album: dict[str, set[int]] = defaultdict(set)
        for t in tracks:
            album = t.get("Album")
            y = valid_year(t.get("Track Year") or t.get("Year") or (t.get("Release Date") or "")[:4])
            if not (album and y):
                continue
            for artist in {t.get("Album Artist"), t.get("Artist")} - {None, ""}:
                by_pair[(norm(artist), norm(album))].append(y)
            by_album[norm(album)].add(y)
        self.by_pair = by_pair
        # 앨범 이름만으로 찾을 때는 연도가 하나뿐인 경우만 믿는다 (아티스트 표기가 달라 못 찾은 경우 보완)
        self.by_album = {a: next(iter(s)) for a, s in by_album.items() if len(s) == 1}

    def get(self, artist, album) -> int | None:
        for title in album_variants(album):
            years = self.by_pair.get((norm(artist), norm(title)))
            if years:
                counts = Counter(years)
                top = max(counts.values())
                return min(y for y, c in counts.items() if c == top)      # 동률이면 이른 연도
        for title in album_variants(album):
            y = self.by_album.get(norm(title))
            if y:
                return y
        return None


def load_apple_years(apple_dir) -> AppleYears | None:
    """폴더 안의 'Apple Music Library Tracks.json(.zip)' 을 읽는다. 없으면 None."""
    if not apple_dir:
        return None
    d = Path(apple_dir)
    try:
        zp, jp = d / "Apple Music Library Tracks.json.zip", d / "Apple Music Library Tracks.json"
        if zp.exists():
            with zipfile.ZipFile(zp) as z:
                name = next(n for n in z.namelist() if n.endswith(".json"))
                return AppleYears(json.loads(z.read(name)))
        if jp.exists():
            return AppleYears(json.loads(jp.read_text(encoding="utf-8")))
    except (OSError, ValueError, StopIteration, zipfile.BadZipFile):
        return None
    return None


# --------------------------------------------------------------------------- MusicBrainz

def _phrase(s: str) -> str:
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


class MusicBrainzClient:
    def __init__(self, gap=REQUEST_GAP, session=None):
        self.gap, self.calls = gap, 0
        self.session = session or requests.Session()

    def search(self, artist, album):
        """(상태, 후보 [{"title", "credits", "year"}]). 상태: ok / error(일시적: 네트워크·503·요청 한도)."""
        params = {"query": f"releasegroup:{_phrase(album)} AND artist:{_phrase(artist)}", "fmt": "json", "limit": SEARCH_LIMIT}
        data = None
        for wait in (0, 2.5, 5, 8):
            time.sleep(wait)
            try:
                r = self.session.get(MB_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=20)
            except requests.RequestException:
                continue
            finally:
                self.calls += 1
                time.sleep(self.gap)
            if r.status_code == 200:
                try:
                    data = r.json()
                except ValueError:
                    continue
                break
            if r.status_code in (400, 404):          # 검색어를 못 쓰는 경우: 일시적 오류가 아니라 "없음"
                return "ok", []
        if data is None:
            return "error", []
        hits = []
        for rg in data.get("release-groups", []):
            y = valid_year(rg.get("first-release-date"))
            if not y:
                continue
            credits = rg.get("artist-credit", [])
            names = ["".join(c.get("name", "") + c.get("joinphrase", "") for c in credits)]
            for c in credits:
                names += [c.get("name", ""), (c.get("artist") or {}).get("name", "")]
            hits.append({"title": rg.get("title", ""), "credits": list(dict.fromkeys(n for n in names if n)), "year": y})
        return "ok", hits


def _artist_matches(want, got) -> bool:
    a, b = norm(want), norm(got)
    if not a or not b:
        return False
    return a == b or (min(len(a), len(b)) >= 3 and (a in b or b in a))


def mb_years(hits, artist, title) -> set[int]:
    """검색 결과 중 앨범 제목이 같고 아티스트가 맞는 항목의 최초 발매 연도들."""
    return {h["year"] for h in hits if norm(h["title"]) == norm(title) and any(_artist_matches(artist, c) for c in h["credits"])}


# --------------------------------------------------------------------------- 결정

def resolve_year(artist, album, mb=None, apple=None) -> dict | None:
    """
    {"year", "src", ...} (못 찾으면 year = None) 또는, 일시적 오류 때문에 판단을 미뤄야 하면 None (캐시하지 않음).
    mb: search(artist, album) 를 가진 객체 (없으면 MusicBrainz 단계를 건너뜀, 테스트에서는 가짜 객체).
    """
    apple_y = apple.get(artist, album) if apple is not None else None
    transient = False
    if mb is not None:
        for title in album_variants(album):
            st, hits = mb.search(artist, title)
            if st == "error":
                transient = True
                continue
            years = mb_years(hits, artist, title)
            if len(years) == 1:
                return {"year": next(iter(years)), "src": "musicbrainz"}
            if years:
                if apple_y in years:
                    return {"year": apple_y, "src": "musicbrainz:apple"}
                return {"year": min(years), "src": "musicbrainz", "ambiguous": sorted(years)}
    if apple_y:
        return {"year": apple_y, "src": "apple", **({"retry": True} if transient else {})}
    return None if transient else {"year": None, "src": None}


def album_pairs(df):
    """앱이 앨범을 세는 방식 그대로의 (대표 아티스트, 앨범, 재생 수), 재생 많은 순."""
    import pandas as pd

    from app.analysis.keys import resolve_all

    keys, reps, names = resolve_all(df, "album")
    valid = keys != ""
    work = pd.DataFrame({"artist": reps[valid], "album": names[valid], "key": keys[valid]})
    counts = work.groupby("key").agg(artist=("artist", "first"), album=("album", "first"), n=("key", "size"))
    return [(r.artist, r.album, int(r.n)) for r in counts.sort_values("n", ascending=False).itertuples()]


def fill_years(pairs, cache, mb=None, apple=None, overrides=None, limit=0, now=None, progress=None) -> dict:
    """
    pairs [(아티스트, 앨범, 재생 수)] 중 아직 모르는 앨범을 재생 많은 순으로 조회해 cache 에 채운다 (cache 를 직접 고친다).
    한 번도 조회하지 않은 앨범이 먼저, 재시도 대상(못 찾았거나 retry 표시)은 그다음이다. 수동 보정이 있는 앨범은 건너뛴다.
    progress(i, total, stats) 는 10개마다 불린다.
    """
    overrides = overrides or {}
    now = now or time.time()
    todo = [(a, b, n) for a, b, n in pairs if override_for(overrides, a, b) is None and needs_lookup(cache.get(cache_key(a, b)), now)]
    todo.sort(key=lambda x: (cache_key(x[0], x[1]) in cache, -x[2]))
    total = len(todo)
    if limit:
        todo = todo[:limit]
    stats = {"found": 0, "unknown": 0, "skipped": 0}
    transient_run = 0
    done = 0
    for i, (artist, album, _n) in enumerate(todo, 1):
        res = resolve_year(artist, album, mb, apple)
        done = i
        if res is None:
            stats["skipped"] += 1                  # 일시적 오류: 저장하지 않고 다음에 다시
        else:
            cache[cache_key(artist, album)] = {**res, "tried": int(time.time())}
            stats["found" if res["year"] else "unknown"] += 1
        # MusicBrainz 에 닿지 않는 상태(오프라인·점검 중)면 계속 두드리지 않고 멈춘다 (남은 앨범은 다음에 이어서)
        transient_run = transient_run + 1 if (res is None or res.get("retry")) else 0
        if progress and i % 10 == 0:
            progress(i, len(todo), stats)
        if transient_run >= MAX_TRANSIENT_RUN:
            break
    return {**stats, "remaining": max(0, total - done), "stopped": transient_run >= MAX_TRANSIENT_RUN}


# --------------------------------------------------------------------------- 조회 (백엔드용)

class AlbumYearLookup:
    """캐시 파일과 수동 보정 파일을 읽어 (아티스트, 앨범) -> {"year", "src"}. 파일이 바뀌면 다시 읽는다."""

    def __init__(self, cache_path, overrides_path=OVERRIDES_PATH):
        self.cache_path, self.overrides_path = Path(cache_path), Path(overrides_path)
        self._sig = None
        self._albums: dict = {}
        self._overrides: dict = {}

    @staticmethod
    def _mtime(p: Path):
        try:
            return p.stat().st_mtime_ns
        except OSError:
            return None

    def _refresh(self):
        sig = (self._mtime(self.cache_path), self._mtime(self.overrides_path))
        if sig != self._sig:
            self._sig = sig
            self._albums = load_cache(self.cache_path)
            self._overrides = load_overrides(self.overrides_path)

    def get(self, artist, album) -> dict | None:
        """수동 보정 > 캐시. 캐시에 항목이 없으면 None(아직 조회 전), 항목은 있는데 연도가 없으면 {"year": None}(못 찾음)."""
        self._refresh()
        y = override_for(self._overrides, artist, album)
        if y:
            return {"year": y, "src": "manual"}
        return self._albums.get(cache_key(artist, album))
