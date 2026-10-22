"""
Overview 의 "Did you know?" 카드 후보. 규칙 기반이라 AI 없이 같은 데이터에서는 같은 후보가 나오고, 화면이 그중 하나를 랜덤으로 보여 준다.

후보 하나는 {"id", "group", "icon", "text"}. 각 생성기는 조건(임계값)을 넘는 흥미로운 사실만 돌려주고, 조건에 안 맞으면 아무것도 돌려주지
않는다 (예: 제목에 'night' 가 들어간 곡이 5개 미만이면 그 후보는 없다). group 은 생성기 이름이라, 후보가 많은 생성기(제목 단어, 마일스톤)가
다른 종류를 밀어내지 않도록 화면이 group 을 먼저 고른 뒤 그 안에서 고른다. 생성기 하나가 실패해도 나머지는 그대로 나온다.
모든 날짜·시간은 KST 기준이고, 전체 기록으로 계산한다.
"""

import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from app.analysis.keys import name_key

KST = ZoneInfo("Asia/Seoul")
WORDS_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config" / "fun_words.txt"
DEFAULT_WORDS = ["night", "love", "rain", "dream", "blue", "sun", "moon", "star", "heart", "summer", "home", "time", "black", "light",
                 "밤", "새벽", "사랑", "이별", "눈물", "바다", "하늘", "여름", "겨울", "꿈"]
WEEKDAYS = "월화수목금토일"

MIN_WORD_TRACKS = 5          # 제목 단어 후보: 그 단어가 들어간 곡 수
MIN_TOP_WORD_TRACKS = 8      # 가장 흔한 제목 단어
MIN_LONG_TITLE = 30          # 가장 긴 제목 글자 수
MAX_SHORT_TITLE = 2          # 가장 짧은 제목 글자 수
MIN_SAME_TITLE_ARTISTS = 3
MIN_SELF_TITLED = 3
MIN_REISSUE_ALBUMS = 10
MIN_REPEAT_IN_DAY = 8
MIN_ARTIST_RUN = 15
RUN_GAP = 3600               # 이 시간(초) 안에 이어진 재생만 "연달아"로 본다
ALBUM_RUN_GAP = 1200
MIN_ALBUM_RUN = 6
MIN_ALBUM_BINGES = 3
MIN_STREAK_DAYS = 14
MIN_DISTINCT_FOR_ONE_PLAY = 50
MIN_COMEBACK_DAYS = 365
MIN_NIGHT_PLAYS = 30
MIN_PLAYS_FOR_SLOT = 200
MIN_FIRST_OF_DAY = 10
MIN_PAST_MIDNIGHT_DAYS = 10
MIN_DAYS_FOR_WEEKEND = 28
MIN_WEEKEND_DIFF_PCT = 10
MIN_BIGGEST_DAY = 50
MIN_NEW_ARTISTS = 3
MIN_FAST_FALL = 15
STOP_TOKENS = {
    "the", "and", "you", "for", "with", "feat", "featuring", "from", "that", "this", "your", "are", "not", "but", "all", "can", "was", "have", "its",
    "remaster", "remastered", "version", "live", "mix", "edit", "original", "mono", "stereo", "remix", "demo", "intro", "outro", "interlude", "untitled",
}
GENERIC_TITLES = {"intro", "outro", "interlude", "untitled", "prelude", "overture", "reprise", "theme", "instrumental", "skit"}
_TOKEN = re.compile(r"[a-z']{3,}|[가-힣]{2,}|[ぁ-んァ-ヶ一-龥]{2,}")
_REISSUE = re.compile(r"remaster|remix|deluxe|anniversary|expanded|reissue|\bmix(?:es)?\b", re.IGNORECASE)


def load_words(path=WORDS_PATH) -> list[str]:
    """config/fun_words.txt 의 단어 목록 (파일이 없거나 비어 있으면 기본 목록)."""
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return list(DEFAULT_WORDS)
    words = [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]
    return words or list(DEFAULT_WORDS)


def _clip(text: str, n: int = 60) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


def ko_date(day) -> str:
    y, m, d = str(day)[:10].split("-")
    return f"{y}년 {int(m)}월 {int(d)}일"


def _fact(group: str, icon: str, text: str, key: str = "") -> dict:
    return {"id": f"{group}:{key}" if key else group, "group": group, "icon": icon, "text": text}


class _Ctx:
    """전체 기록을 한 번만 정리해 두고 생성기들이 같이 쓴다."""

    def __init__(self, df: pd.DataFrame, today: date, words: list[str]):
        d = df[["uts", "artist", "album", "track"]].copy()
        for c in ("artist", "album", "track"):
            d[c] = d[c].fillna("").astype(str)
        d["uts"] = pd.to_numeric(d["uts"], errors="coerce")
        d = d.dropna(subset=["uts"]).sort_values("uts", kind="stable").reset_index(drop=True)
        d["uts"] = d["uts"].astype("int64")
        dt = pd.to_datetime(d["uts"], unit="s", utc=True).dt.tz_convert(KST)
        d["day"] = dt.dt.strftime("%Y-%m-%d")
        d["month"] = dt.dt.strftime("%Y-%m")
        d["md"] = dt.dt.strftime("%m-%d")
        d["year"] = dt.dt.year
        d["hour"] = dt.dt.hour
        d["wd"] = dt.dt.weekday

        def nk(col):
            return d[col].map({v: name_key(v) if v else "" for v in d[col].unique()})

        d["akey"] = nk("artist")
        d["alnk"] = nk("album")
        d["tnk"] = nk("track")
        d["tkey"] = (d["akey"] + "\t" + d["tnk"]).where((d["artist"] != "") & (d["track"] != ""), "")
        d["alkey"] = (d["akey"] + "\t" + d["alnk"]).where((d["artist"] != "") & (d["album"] != ""), "")
        self.d, self.today, self.words = d, today, words
        self.t = d[d["tkey"] != ""]
        self.uniq = self.t.groupby("tkey").agg(artist=("artist", "first"), track=("track", "first"), tnk=("tnk", "first"), akey=("akey", "first"), plays=("tkey", "size"))
        al = d[d["alkey"] != ""]
        self.albums = al.groupby("alkey").agg(artist=("artist", "first"), album=("album", "first"), alnk=("alnk", "first"), akey=("akey", "first"), plays=("alkey", "size"))

    def row_text(self, r) -> str:
        return f"{r['artist']}의 ‘{r['track']}’"


# --------------------------------------------------------------------------- 처음과 기념일

def _first_ever(c: _Ctx):
    r = c.t.iloc[0]
    return [_fact("first_ever", "🌱", f"가장 처음 기록된 스크로블은 {c.row_text(r)} 곡이에요 ({ko_date(r['day'])}).")]


def _first_this_year(c: _Ctx):
    year = int(c.d["year"].max())
    rows = c.t[c.t["year"] == year]
    if rows.empty or rows.index[0] == c.t.index[0]:
        return []
    r = rows.iloc[0]
    label = "올해" if year == c.today.year else f"{year}년"
    return [_fact("first_year", "🎆", f"{label} 첫 스크로블은 {c.row_text(r)} 곡이에요 ({ko_date(r['day'])}).")]


def _on_this_day(c: _Ctx):
    past = c.d[(c.d["md"] == c.today.strftime("%m-%d")) & (c.d["year"] < c.today.year)]
    if past.empty:
        return []
    counts = past.groupby("year").size()
    year = int(counts[counts == counts.max()].index.max())             # 가장 많이 들은 해 (동률이면 가까운 해)
    rows = past[(past["year"] == year) & (past["tkey"] != "")]
    if rows.empty:
        return []
    top = rows.groupby("tkey").agg(artist=("artist", "first"), track=("track", "first"), n=("tkey", "size")).sort_values(["n", "track"], ascending=[False, True]).iloc[0]
    when = f"{c.today.year - year}년 전 오늘({ko_date(rows.iloc[0]['day'])})"
    more = f" 등 {len(rows)}곡을" if len(rows) > 1 else " 한 곡을"
    return [_fact("on_this_day", "📅", f"{when}은 {top['artist']}의 ‘{top['track']}’{more} 들었어요.")]


def _milestones(c: _Ctx):
    total, out = len(c.d), []
    for n in sorted({1000, 5000} | set(range(10000, total + 1, 10000))):
        if n <= total:
            r = c.d.iloc[n - 1]
            if r["track"] and r["artist"]:
                out.append(_fact("milestone", "🏁", f"{n:,}번째 스크로블은 {c.row_text(r)} 곡이었어요 ({ko_date(r['day'])}).", str(n)))
    return out


# --------------------------------------------------------------------------- 제목 말놀이

def _word_pattern(word: str):
    w = word.lower()
    if w.isascii():
        return re.compile(rf"(?<![a-z]){re.escape(w)}s?(?![a-z])")
    return re.compile(re.escape(w))


def _title_words(c: _Ctx):
    titles = c.uniq["track"].str.lower()
    out = []
    for word in dict.fromkeys(c.words):
        hit = titles.str.contains(_word_pattern(word), regex=True)
        n = int(hit.sum())
        if n >= MIN_WORD_TRACKS:
            plays = int(c.uniq.loc[hit, "plays"].sum())
            out.append(_fact("title_word", "🔤", f"제목에 ‘{word}’ 단어가 들어간 곡을 {n:,}개 들었어요 (재생 {plays:,}회).", word))
    return out


def _top_title_word(c: _Ctx):
    counts = Counter()
    for title in c.uniq["track"].str.lower():
        counts.update({t for t in _TOKEN.findall(title) if t not in STOP_TOKENS})
    if not counts:
        return []
    word, n = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0]
    if n < MIN_TOP_WORD_TRACKS:
        return []
    return [_fact("top_word", "🏷️", f"내가 들은 곡 제목에서 가장 자주 나온 단어는 ‘{word}’ ({n:,}곡)이에요.")]


def _title_length(c: _Ctx):
    lens = c.uniq["track"].str.len()
    out = []
    longest = c.uniq.loc[lens.idxmax()]
    if lens.max() >= MIN_LONG_TITLE:
        out.append(_fact("long_title", "📏", f"가장 긴 곡 제목은 {int(lens.max())}글자예요: ‘{_clip(longest['track'])}’ — {longest['artist']}", "long"))
    short = c.uniq[lens <= MAX_SHORT_TITLE].sort_values("plays", ascending=False)
    if len(short):
        r = short.iloc[0]
        out.append(_fact("long_title", "🔹", f"가장 짧은 곡 제목은 ‘{r['track']}’ ({r['artist']}), {len(r['track'])}글자예요.", "short"))
    return out


def _same_title(c: _Ctx):
    u = c.uniq[~c.uniq["tnk"].isin({name_key(g) for g in GENERIC_TITLES})]
    g = u.groupby("tnk").agg(n=("akey", "nunique"), track=("track", "first"), plays=("plays", "sum")).sort_values(["n", "plays"], ascending=False)
    if g.empty or g.iloc[0]["n"] < MIN_SAME_TITLE_ARTISTS:
        return []
    r = g.iloc[0]
    return [_fact("same_title", "👯", f"‘{r['track']}’ 라는 제목의 곡을 {int(r['n'])}명의 아티스트에게서 들었어요.")]


def _self_titled(c: _Ctx):
    s = c.albums[c.albums["alnk"] == c.albums["akey"]].sort_values("plays", ascending=False)
    if len(s) < MIN_SELF_TITLED:
        return []
    names = ", ".join(s["artist"].head(2))
    return [_fact("self_titled", "🪞", f"앨범 제목이 아티스트 이름과 같은 ‘셀프 타이틀’ 앨범을 {len(s)}개 들었어요 (예: {names}).")]


def _reissues(c: _Ctx):
    n = int(c.albums["album"].str.contains(_REISSUE, regex=True).sum())
    if n < MIN_REISSUE_ALBUMS:
        return []
    return [_fact("reissue", "💿", f"리마스터·에디션 표기가 붙은 앨범을 {n:,}개 들었어요.")]


# --------------------------------------------------------------------------- 반복과 몰입

def _repeat_in_day(c: _Ctx):
    if c.t.empty:
        return []
    per = c.t.groupby(["day", "tkey"]).size()
    n = int(per.max())
    if n < MIN_REPEAT_IN_DAY:
        return []
    day, tkey = per.idxmax()
    r = c.uniq.loc[tkey]
    return [_fact("repeat_day", "🔁", f"하루에 같은 곡을 {n}번 반복한 날이 있어요: {ko_date(day)}, {c.row_text(r)}.")]


def _runs(c: _Ctx, key: str, gap: int) -> pd.DataFrame:
    """같은 key(비어 있지 않은) 재생이 gap 초 안에 이어진 구간: 구간 시작 행의 정보와 길이."""
    d = c.d
    new = (d[key] != d[key].shift()) | (d["uts"].diff() > gap) | (d[key] == "")
    run = new.cumsum()
    g = d[d[key] != ""].groupby(run[d[key] != ""]).agg(key=(key, "first"), artist=("artist", "first"), album=("album", "first"), day=("day", "first"), n=(key, "size"))
    return g


def _artist_run(c: _Ctx):
    runs = _runs(c, "akey", RUN_GAP)
    if runs.empty or runs["n"].max() < MIN_ARTIST_RUN:
        return []
    r = runs.sort_values("n", ascending=False).iloc[0]
    return [_fact("artist_run", "🎧", f"{r['artist']}만 연달아 {int(r['n'])}곡을 들은 적이 있어요 ({ko_date(r['day'])}).")]


def _album_binge(c: _Ctx):
    runs = _runs(c, "alkey", ALBUM_RUN_GAP)
    runs = runs[runs["n"] >= MIN_ALBUM_RUN]
    if len(runs) < MIN_ALBUM_BINGES:
        return []
    top = runs.groupby("key").agg(artist=("artist", "first"), album=("album", "first"), n=("n", "size")).sort_values(["n", "album"], ascending=[False, True]).iloc[0]
    return [_fact("album_binge", "📀", f"앨범 하나를 이어서 통째로 듣는 정주행({MIN_ALBUM_RUN}곡 이상)이 {len(runs)}번 있었어요. 가장 자주 정주행한 앨범은 ‘{top['album']}’ — {top['artist']} ({int(top['n'])}번)이에요.")]


def _streak(c: _Ctx):
    days = pd.to_datetime(pd.Series(sorted(c.d["day"].unique())))
    if days.empty:
        return []
    grp = (days.diff().dt.days != 1).cumsum()
    sizes = days.groupby(grp).agg(["size", "first", "last"])
    best = sizes.sort_values(["size", "first"], ascending=[False, False]).iloc[0]
    if best["size"] < MIN_STREAK_DAYS:
        return []
    return [_fact("streak", "🔥", f"최장 {int(best['size'])}일 연속으로 음악을 들었어요 ({ko_date(best['first'].strftime('%Y-%m-%d'))} ~ {ko_date(best['last'].strftime('%Y-%m-%d'))}).")]


def _one_play(c: _Ctx):
    n = len(c.uniq)
    if n < MIN_DISTINCT_FOR_ONE_PLAY:
        return []
    once = int((c.uniq["plays"] == 1).sum())
    return [_fact("one_play", "☝️", f"들은 곡 {n:,}개 중 {round(once / n * 100)}%({once:,}곡)는 딱 한 번만 들었어요.")]


def _comeback(c: _Ctx):
    gaps = c.t.groupby("tkey")["uts"].diff()
    if not gaps.notna().any():
        return []
    i = gaps.idxmax()
    secs = int(gaps[i])
    if secs < MIN_COMEBACK_DAYS * 86400:
        return []
    r = c.t.loc[i]
    days = secs // 86400
    span = f"{days // 365}년" + (f" {days % 365 // 30}개월" if days % 365 // 30 else "")
    before = datetime.fromtimestamp(int(r["uts"]) - secs, KST).strftime("%Y-%m-%d")
    return [_fact("comeback", "↩️", f"{span} 만에 다시 들은 곡이 있어요: {c.row_text(r)} ({ko_date(before)} → {ko_date(r['day'])}).")]


# --------------------------------------------------------------------------- 시간대

def _night_owl(c: _Ctx):
    n = c.d[c.d["hour"].isin([3, 4, 5])]
    if len(n) < MIN_NIGHT_PLAYS:
        return []
    top = n[n["artist"] != ""]["artist"].value_counts()
    extra = f" 그 시간대의 단골은 {top.index[0]} ({int(top.iloc[0])}회)예요." if len(top) else ""
    return [_fact("night_owl", "🌙", f"새벽 3~5시에 들은 곡이 {len(n):,}개예요.{extra}")]


def _favorite_slot(c: _Ctx):
    if len(c.d) < MIN_PLAYS_FOR_SLOT:
        return []
    per = c.d.groupby(["wd", "hour"]).size()
    wd, hour = per.idxmax()
    return [_fact("favorite_slot", "⏰", f"가장 많이 음악을 듣는 시간은 {WEEKDAYS[wd]}요일 {hour}시 무렵이에요 ({int(per.max()):,}회).")]


def _first_of_day(c: _Ctx):
    first = c.d.drop_duplicates("day")
    first = first[first["artist"] != ""]["artist"].value_counts()
    if first.empty or first.iloc[0] < MIN_FIRST_OF_DAY:
        return []
    return [_fact("first_of_day", "☀️", f"하루의 첫 곡을 가장 많이 맡은 아티스트는 {first.index[0]} ({int(first.iloc[0])}일)이에요.")]


def _past_midnight(c: _Ctx):
    late = c.d.loc[c.d["hour"] < 5, "day"].nunique()
    total = c.d["day"].nunique()
    if late < MIN_PAST_MIDNIGHT_DAYS:
        return []
    return [_fact("past_midnight", "🦉", f"자정을 넘겨 새벽 5시 전까지 들은 날이 {late}일이에요 (음악을 들은 {total:,}일 중 {round(late / total * 100)}%).")]


def _weekend(c: _Ctx):
    span = pd.date_range(c.d["day"].iloc[0], c.d["day"].iloc[-1])
    if len(span) < MIN_DAYS_FOR_WEEKEND:
        return []
    we_days = int((span.weekday >= 5).sum())
    wk_days = len(span) - we_days
    we_plays = int((c.d["wd"] >= 5).sum())
    wk_plays = len(c.d) - we_plays
    if not we_days or not wk_days or not wk_plays:
        return []
    we, wk = we_plays / we_days, wk_plays / wk_days
    pct = round((we / wk - 1) * 100)
    if abs(pct) < MIN_WEEKEND_DIFF_PCT:
        return []
    return [_fact("weekend", "🛋️", f"주말에는 평일보다 하루 평균 {abs(pct)}% 더 {'들어요' if pct > 0 else '적게 들어요'} (주말 {we:.0f}곡 vs 평일 {wk:.0f}곡).")]


def _biggest_day(c: _Ctx):
    per = c.d.groupby("day").size()
    n = int(per.max())
    if n < MIN_BIGGEST_DAY:
        return []
    day = per.idxmax()
    top = c.d[(c.d["day"] == day) & (c.d["artist"] != "")]["artist"].value_counts()
    extra = f" 그날의 주인공은 {top.index[0]} ({int(top.iloc[0])}곡)이에요." if len(top) else ""
    return [_fact("biggest_day", "🏔️", f"하루에 가장 많이 들은 날은 {ko_date(day)}, 무려 {n:,}곡이에요.{extra}")]


# --------------------------------------------------------------------------- 발견

def _new_artists(c: _Ctx):
    d = c.d[c.d["artist"] != ""]
    if d.empty:
        return []
    month = d["month"].iloc[-1]
    first = d.drop_duplicates("akey")
    if month == d["month"].iloc[0]:                    # 기록의 첫 달은 모두 "처음"이라 의미가 없다
        return []
    new = set(first.loc[first["month"] == month, "akey"])
    if len(new) < MIN_NEW_ARTISTS:
        return []
    top = d[(d["month"] == month) & d["akey"].isin(new)]["artist"].value_counts()
    y, m = month.split("-")
    label = "이번 달" if month == c.today.strftime("%Y-%m") else f"{y}년 {int(m)}월"
    return [_fact("new_artists", "🆕", f"{label}에 처음 들은 아티스트가 {len(new)}명이에요. 그중 가장 많이 들은 아티스트는 {top.index[0]} ({int(top.iloc[0])}회)예요.")]


def _fast_fall(c: _Ctx):
    d = c.d[c.d["artist"] != ""]
    if d.empty:
        return []
    start, end = int(d["uts"].iloc[0]), int(d["uts"].iloc[-1])
    first = d.drop_duplicates("akey").set_index("akey")["uts"]
    first = first[(first >= start + 14 * 86400) & (first + 7 * 86400 <= end)]      # 기록 초반부터 있던 아티스트와, 아직 일주일이 안 지난 아티스트는 뺀다
    if first.empty:
        return []
    j = d[d["akey"].isin(first.index)].copy()
    j["first"] = j["akey"].map(first)
    near = j[j["uts"] - j["first"] < 7 * 86400].groupby("akey").agg(n=("akey", "size"), artist=("artist", "first"), day=("day", "first")).sort_values("n", ascending=False)
    if near.empty or near.iloc[0]["n"] < MIN_FAST_FALL:
        return []
    r = near.iloc[0]
    return [_fact("fast_fall", "💘", f"처음 들은 뒤 일주일 만에 {int(r['n'])}번이나 들은 아티스트는 {r['artist']} (첫 재생 {ko_date(r['day'])})이에요.")]


GENERATORS = [
    _first_ever, _first_this_year, _on_this_day, _milestones,
    _title_words, _top_title_word, _title_length, _same_title, _self_titled, _reissues,
    _repeat_in_day, _artist_run, _album_binge, _streak, _one_play, _comeback,
    _night_owl, _favorite_slot, _first_of_day, _past_midnight, _weekend, _biggest_day,
    _new_artists, _fast_fall,
]


def build_facts(df: pd.DataFrame, today: date | None = None, words: list[str] | None = None) -> list[dict]:
    """조건을 넘는 모든 후보. 생성기 하나가 실패해도 나머지는 그대로 나온다."""
    if df is None or len(df) == 0 or not {"uts", "artist", "album", "track"} <= set(df.columns):
        return []
    c = _Ctx(df, today or datetime.now(KST).date(), words if words is not None else load_words())
    if c.t.empty:
        return []
    facts: list[dict] = []
    for gen in GENERATORS:
        try:
            facts += gen(c)
        except Exception:                                  # noqa: BLE001  하나가 깨져도 카드는 나온다
            continue
    return facts
