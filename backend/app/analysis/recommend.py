"""
오늘의 추천 앨범. AI 없이 기록에서 규칙으로만 고른다 (같은 기록·같은 날·같은 salt 면 항상 같은 결과).

세 가지 기준 (기준일 = 기록의 마지막 날짜, 앨범은 앱의 다른 화면과 같은 방식(resolve_all)으로 묶는다):
  1. dormant   "다시 들어볼 앨범": 예전에 꽤 들었는데(재생 dormant_min_plays 회 이상, 서로 다른 dormant_min_days 일 이상) 마지막으로 들은 지 dormant_days 일 넘은 앨범.
               많이 들었을수록, 오래 안 들었을수록 점수가 높다.
  2. once      "한 번만 들은 앨범": 하루(한 번의 청취)만 듣고 그 뒤로 안 들은 앨범. 우연히 한 곡만 들은 것은 빼도록 재생 once_min_plays 회 이상,
               그 뒤로 once_min_age_days 일 이상 지난 앨범만 본다. 그 아티스트를 많이 들었을수록 점수가 높다.
  3. challenge "도전": 많이 듣는 아티스트(상위 challenge_top_artists 명)의 앨범 중 거의 안 들어 본 앨범 (그 아티스트의 가장 많이 들은 앨범 재생의
               challenge_max_ratio 배 이하, 들은 날 challenge_max_days 일 이하). 좋아하는 아티스트일수록, 격차가 클수록 점수가 높다.

점수 순 상위 pool 개 중에서 점수를 가중치로 per_category 개를 뽑는다 (날짜 + salt 로 시드를 고정한 의사 난수라, 하루 동안은 그대로이고 salt 를 올리면 "다시 뽑기").
한 앨범은 한 기준에서만 나온다. 기준값은 config/recommend.txt (`키 = 값`, # 주석) 로 바꿀 수 있고, 없거나 잘못된 값이면 기본값을 쓴다.
"""

import hashlib
import math
import random
import re
from datetime import date
from pathlib import Path

import pandas as pd

from app.analysis.keys import name_key, resolve_all

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent.parent / "config" / "recommend.txt"

DEFAULTS: dict[str, float] = {
    "dormant_days": 150,
    "dormant_min_plays": 15,
    "dormant_min_days": 3,
    "once_min_plays": 3,
    "once_min_age_days": 30,
    "challenge_top_artists": 30,
    "challenge_max_ratio": 0.2,
    "challenge_max_days": 2,
    "exclude_singles": 1,       # 1 이면 "- Single" 로 끝나는 앨범은 한 번만 들은 앨범·도전에서 뺀다 (곡 하나짜리라 앨범으로 권하기 어렵다)
    "per_category": 3,
    "pool": 12,
}

CATEGORIES = [
    ("dormant", "다시 들어볼 앨범", "예전에 많이 들었는데 한동안 안 들은 앨범"),
    ("once", "한 번만 들은 앨범", "하루만 듣고 그 뒤로 다시 안 들은 앨범"),
    ("challenge", "도전", "많이 듣는 아티스트의 거의 안 들어 본 앨범"),
]


_SINGLE = re.compile(r"[-–—(]\s*single\)?\s*$", re.IGNORECASE)


def load_config(path: Path | None = None) -> dict[str, float]:
    """기본값 위에 config/recommend.txt 의 `키 = 값` 을 덮어쓴다. 모르는 키·숫자가 아닌 값·음수는 무시한다."""
    cfg = dict(DEFAULTS)
    try:
        text = Path(path or CONFIG_PATH).read_text(encoding="utf-8-sig")
    except OSError:
        return cfg
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key not in DEFAULTS:
            continue
        try:
            number = float(value.strip())
        except ValueError:
            continue
        if number >= 0 and math.isfinite(number):
            cfg[key] = number
    return cfg


def album_table(df: pd.DataFrame) -> pd.DataFrame:
    """앨범(키)별 재생 수·들은 날 수·곡 수·처음/마지막으로 들은 날 + 대표 아티스트와 이름. 아티스트별 재생 수도 붙인다."""
    keys, reps, names = resolve_all(df, "album")
    kst = pd.to_datetime(df["utc_time"], utc=True, format="mixed").dt.tz_convert("Asia/Seoul")
    work = pd.DataFrame({
        "key": keys, "artist": reps, "name": names,
        "day": kst.dt.strftime("%Y-%m-%d"),
        "track": df["track"].fillna("").astype(str).map(name_key),
    })
    work = work[work["key"] != ""]
    if work.empty:
        return pd.DataFrame(columns=["name", "artist", "plays", "days", "tracks", "first", "last", "artist_plays", "artist_max"])
    g = work.groupby("key")
    table = pd.DataFrame({"plays": g.size(), "days": g["day"].nunique(), "tracks": g["track"].nunique(),
                          "first": g["day"].min(), "last": g["day"].max()})
    head = work.drop_duplicates("key").set_index("key")[["name", "artist"]]
    table = head.join(table)
    artist_plays = table.groupby("artist")["plays"].sum()
    table["artist_plays"] = table["artist"].map(artist_plays)
    table["artist_max"] = table.groupby("artist")["plays"].transform("max")
    return table


def _age_text(days: int) -> str:
    if days >= 365:
        years, rest = divmod(days, 365)
        return f"{years}년 {rest // 30}개월" if rest >= 30 else f"{years}년"
    return f"{days // 30}개월" if days >= 60 else f"{days}일"


def _candidates(table: pd.DataFrame, ref: pd.Timestamp, cfg: dict) -> dict[str, list[dict]]:
    if table.empty:
        return {c: [] for c, _, _ in CATEGORIES}
    t = table.copy()
    t["age"] = (ref - pd.to_datetime(t["last"])).dt.days.clip(lower=0)
    artist_rank = t.drop_duplicates("artist").sort_values("artist_plays", ascending=False)["artist"].tolist()
    top_artists = set(artist_rank[: int(cfg["challenge_top_artists"])])
    max_artist = max(1, int(t["artist_plays"].max()))

    def row(key, r, reason, score):
        return {"key": key, "name": r["name"], "artist": r["artist"] or None, "plays": int(r["plays"]), "days": int(r["days"]),
                "tracks": int(r["tracks"]), "first_played": r["first"], "last_played": r["last"], "days_since": int(r["age"]),
                "artist_plays": int(r["artist_plays"]), "reason": reason, "score": round(float(score), 4)}

    out: dict[str, list[dict]] = {c: [] for c, _, _ in CATEGORIES}
    for key, r in t.iterrows():
        plays, days, age = int(r["plays"]), int(r["days"]), int(r["age"])
        single = bool(cfg["exclude_singles"]) and bool(_SINGLE.search(r["name"]))
        if plays >= cfg["dormant_min_plays"] and days >= cfg["dormant_min_days"] and age >= cfg["dormant_days"]:
            score = math.log1p(plays) * (0.5 + min(age, 1095) / 365)
            out["dormant"].append(row(key, r, f"{plays}번 들었던 앨범인데 마지막으로 들은 지 {_age_text(age)}({r['last']}) 됐어요", score))
        elif not single and days == 1 and plays >= cfg["once_min_plays"] and age >= cfg["once_min_age_days"]:
            score = math.log1p(r["artist_plays"]) * (1 + min(age, 730) / 730)
            out["once"].append(row(key, r, f"{r['first']}에 하루만 들은 앨범이에요 ({int(r['tracks'])}곡, {plays}회) · 아티스트 총 {int(r['artist_plays'])}회 재생", score))
        if (not single and r["artist"] in top_artists and days <= cfg["challenge_max_days"] and plays <= cfg["challenge_max_ratio"] * r["artist_max"]
              and r["artist_max"] > plays):
            share = math.log1p(r["artist_plays"]) / math.log1p(max_artist)
            score = share * (1 - plays / r["artist_max"])
            out["challenge"].append(row(key, r, f"아티스트는 총 {int(r['artist_plays'])}회 들었는데 이 앨범은 {plays}회뿐이에요 (가장 많이 들은 앨범은 {int(r['artist_max'])}회)", score))
    for c in out:
        out[c].sort(key=lambda d: (-d["score"], d["key"]))
    return out


def _pick(cands: list[dict], n: int, pool: int, rng: random.Random, used: set[str]) -> list[dict]:
    """점수 상위 pool 개에서 점수 비례로 n 개를 뽑는다 (이미 다른 기준에서 나온 앨범은 제외)."""
    avail = [c for c in cands if c["key"] not in used][:pool]
    picks = []
    while avail and len(picks) < n:
        total = sum(max(c["score"], 1e-9) for c in avail)
        x, acc = rng.random() * total, 0.0
        for i, c in enumerate(avail):
            acc += max(c["score"], 1e-9)
            if x <= acc:
                picks.append(avail.pop(i))
                break
        else:
            picks.append(avail.pop())
    return picks


def build_recommendations(df: pd.DataFrame, today: str | None = None, salt: int = 0, cfg: dict | None = None) -> dict:
    cfg = cfg or load_config()
    seed_day = today or date.today().isoformat()
    empty = {"date": seed_day, "salt": salt, "ref": None, "categories": [{"id": c, "label": l, "hint": h, "total": 0, "picks": []} for c, l, h in CATEGORIES]}
    if df is None or len(df) == 0:
        return empty
    table = album_table(df)
    if table.empty:
        return empty
    ref = pd.to_datetime(table["last"]).max()
    cands = _candidates(table, ref, cfg)
    used: set[str] = set()
    cats = []
    for cid, label, hint in CATEGORIES:
        rng = random.Random(int(hashlib.sha256(f"{seed_day}|{salt}|{cid}".encode()).hexdigest(), 16))
        picks = _pick(cands[cid], int(cfg["per_category"]), int(cfg["pool"]), rng, used)
        used.update(p["key"] for p in picks)
        cats.append({"id": cid, "label": label, "hint": hint, "total": len(cands[cid]), "picks": [{k: v for k, v in p.items() if k not in ("key", "score")} for p in picks]})
    return {"date": seed_day, "salt": salt, "ref": ref.strftime("%Y-%m-%d"), "categories": cats}
