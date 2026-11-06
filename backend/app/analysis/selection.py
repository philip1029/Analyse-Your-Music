"""
선택한 아티스트·앨범(하나 또는 여러 개)의 기록만 뽑아 내거나, 그것만 담은 AI 분석용 프롬프트를 만든다.

항목은 {"kind": "artist", "name"} 또는 {"kind": "album", "name", "artist"} 이고, 앨범은 Library 의 앨범 페이지와 같은 기준(select_rows)으로 찾는다.
여러 개를 고르면 기록을 합집합으로 모은다 (아티스트와 그 앨범을 같이 골라도 한 번만 센다). AI 는 쓰지 않고 계산된 수치·표만 만든다.
기간 필터가 걸린 df 를 받으면 그 기간 안의 기록만 쓴다 (라이브러리 전체 대비 비중도 그 기간 기준).
"""

import json
from io import StringIO

import pandas as pd

from app.analysis import taste
from app.analysis.ai_prompt import _sparkline, _table
from app.analysis.keys import name_key, resolve_all
from app.analysis.library import rank_info, select_rows
from app.analysis.listening_time import attach_durations, fmt_hm

MAX_ITEMS = 50
WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


def normalize_items(items) -> list[dict]:
    """입력을 {"kind", "name", "artist"} 로 정리하고, 잘못된 항목·중복은 버린다 (최대 MAX_ITEMS)."""
    out, seen = [], set()
    for it in items or []:
        if not isinstance(it, dict):
            continue
        kind, name = it.get("kind"), str(it.get("name") or "").strip()
        if kind not in ("artist", "album") or not name:
            continue
        artist = (str(it.get("artist")).strip() or None) if kind == "album" and it.get("artist") else None
        ident = (kind, name_key(name), name_key(artist) if artist else "")
        if ident in seen:
            continue
        seen.add(ident)
        out.append({"kind": kind, "name": name, "artist": artist})
    return out[:MAX_ITEMS]


def label(item: dict) -> str:
    if item["kind"] == "album" and item.get("artist"):
        return f"{item['artist']} - {item['name']}"
    return item["name"]


def item_rows(df: pd.DataFrame, item: dict) -> pd.DataFrame:
    if item["kind"] == "artist":
        return df[df["artist"] == item["name"]]
    return select_rows(df, "album", item.get("artist"), item["name"])


def select_df(df: pd.DataFrame, items: list[dict]) -> pd.DataFrame:
    """항목들의 기록 합집합 (원래 행 순서·인덱스 유지)."""
    keep = pd.Series(False, index=df.index)
    for it in items:
        rows = item_rows(df, it)
        keep.loc[rows.index] = True
    return df[keep]


def _kst(df: pd.DataFrame) -> pd.Series:
    return pd.to_datetime(df["utc_time"], utc=True, format="mixed").dt.tz_convert("Asia/Seoul")


def _span(rows: pd.DataFrame) -> tuple[str | None, str | None]:
    if rows.empty:
        return None, None
    kst = _kst(rows)
    return kst.min().strftime("%Y-%m-%d"), kst.max().strftime("%Y-%m-%d")


def summarize(df: pd.DataFrame, items: list[dict]) -> dict:
    """항목별 재생 수·처음/마지막 날짜(없으면 found=False)와 합집합 합계. 화면의 선택 목록 미리보기에 쓴다."""
    out = []
    for it in items:
        rows = item_rows(df, it)
        first, last = _span(rows)
        out.append({**it, "label": label(it), "found": not rows.empty, "scrobbles": int(len(rows)), "first_played": first, "last_played": last})
    union = select_df(df, items)
    first, last = _span(union)
    return {"items": out, "total": {"scrobbles": int(len(union)), "library": int(len(df)), "first_played": first, "last_played": last}}


def export_csv(df: pd.DataFrame, items: list[dict]) -> str:
    """선택한 항목의 기록을 최신순 CSV 로 (한국 시간 열 포함). 엑셀에서 한글이 깨지지 않게 BOM 을 붙인다."""
    sel = select_df(df, items)
    cols = [c for c in ("uts", "utc_time", "artist", "album", "track", "source") if c in sel.columns]
    out = sel[cols].copy()
    if len(out):
        out.insert(2, "kst_time", _kst(sel).dt.strftime("%Y-%m-%d %H:%M:%S"))
        out = out.sort_values("uts", ascending=False, kind="stable") if "uts" in out.columns else out
    else:
        out.insert(2, "kst_time", pd.Series(dtype=str))
    buf = StringIO()
    out.to_csv(buf, index=False)
    return "﻿" + buf.getvalue()


def _tags(artist: str) -> list[str]:
    """캐시에 있는 Last.fm 태그 상위 5개 (없으면 빈 목록)."""
    path = taste.CACHE_DIR / f"{taste._slugify(taste.resolve_artist_name(artist))}.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return [str(t.get("name")) for t in data[:5] if t.get("name")]


def _monthly(rows: pd.DataFrame, months: list[str]) -> list[int]:
    counts = _kst(rows).dt.strftime("%Y-%m").value_counts() if len(rows) else pd.Series(dtype=int)
    return [int(counts.get(m, 0)) for m in months]


def _rank_text(df: pd.DataFrame, item: dict, rows: pd.DataFrame) -> str:
    if rows.empty:
        return "-"
    if item["kind"] == "artist":
        r = rank_info(df, "artist", name=item["name"])
    else:
        r = rank_info(df, "album", key=resolve_all(df, "album")[0].loc[rows.index[0]])
    return f"{r['plays']}위 / {r['total']:,}" if r.get("plays") else "-"


def _seconds(rows: pd.DataFrame) -> int:
    return int(attach_durations(rows)["dur_sec"].fillna(0).sum()) if len(rows) else 0


def _top(rows: pd.DataFrame, column: str, n: int = 10) -> list[tuple[str, int]]:
    """곡·앨범은 앱의 다른 화면과 같은 묶음(resolve_all)으로 센다. 반환: [(표시 이름, 재생 수)]."""
    keys, _, names = resolve_all(rows, column)
    valid = keys != ""
    if not valid.any():
        return []
    counts = keys[valid].value_counts().head(n)
    shown = pd.DataFrame({"k": keys[valid], "n": names[valid]}).drop_duplicates("k").set_index("k")["n"]
    return [(shown[k], int(c)) for k, c in counts.items()]


def build_selection_prompt(df: pd.DataFrame, items: list[dict]) -> dict:
    """선택 항목만 담은 AI 분석용 프롬프트. 반환: {"prompt": 글, "scrobbles": 합집합 재생 수}. 기록이 없으면 prompt 가 None."""
    items = normalize_items(items)
    union = select_df(df, items)
    if union.empty:
        return {"prompt": None, "scrobbles": 0}
    kst_all, kst_sel = _kst(df), _kst(union)
    first, last = kst_sel.min().strftime("%Y-%m-%d"), kst_sel.max().strftime("%Y-%m-%d")
    months = [str(p) for p in pd.period_range(kst_all.min().strftime("%Y-%m"), kst_all.max().strftime("%Y-%m"), freq="M")]
    share = len(union) / len(df) * 100

    lines = [
        "당신은 음악 청취 데이터를 분석하는 전문가입니다. 아래는 제 Last.fm 청취 기록 중 제가 고른 아티스트·앨범만 뽑아 정리한 수치 데이터입니다 "
        "(해석은 최소화하고 계산된 수치/표 위주입니다). 이 데이터를 바탕으로 분석해 주세요.\n",
        "## 1. 선택 개요",
        f"- 선택한 항목: {len(items)}개 ({', '.join(label(i) for i in items)})",
        f"- 기록 기간(전체 라이브러리): {kst_all.min().strftime('%Y-%m-%d')} ~ {kst_all.max().strftime('%Y-%m-%d')}",
        f"- 선택 항목 재생(합집합, 겹치는 기록은 한 번만): {len(union):,}회 = 전체 {len(df):,}회의 {share:.1f}%",
        f"- 선택 항목 청취 시간(추정): {fmt_hm(_seconds(union))} (곡 길이를 아는 재생만, 스크로블 횟수 x 곡 길이)",
        f"- 처음 들은 날 ~ 마지막으로 들은 날: {first} ~ {last}",
        f"- 들은 날 수: {kst_sel.dt.strftime('%Y-%m-%d').nunique():,}일",
        "",
    ]

    rows_by_item = [(it, item_rows(df, it)) for it in items]
    table_rows = []
    for it, rows in rows_by_item:
        f, l = _span(rows)
        table_rows.append([label(it), "아티스트" if it["kind"] == "artist" else "앨범", f"{len(rows):,}", fmt_hm(_seconds(rows)), f or "-", l or "-", _rank_text(df, it, rows)])
    lines += ["### 항목별 요약", _table(["항목", "종류", "재생", "청취 시간", "처음", "마지막", "라이브러리 내 순위(재생)"], table_rows), ""]

    # 월별 추이: 선택 합집합과 항목별 (왼쪽 = 과거), 라이브러리 전체 대비 비중
    lines.append("## 2. 월별 재생 추이")
    sel_monthly = _monthly(union, months)
    all_monthly = _monthly(df, months)
    pct = [round(a / b * 100, 1) if b else 0.0 for a, b in zip(sel_monthly, all_monthly)]
    lines.append(f"기간: {months[0]} ~ {months[-1]}")
    trend = [["선택 전체", _sparkline(sel_monthly), max(sel_monthly), months[sel_monthly.index(max(sel_monthly))]]]
    for it, rows in rows_by_item:
        m = _monthly(rows, months)
        trend.append([label(it), _sparkline(m), max(m) if m else 0, months[m.index(max(m))] if m and max(m) else "-"])
    lines += [_table(["항목", "추이(왼쪽=과거 → 오른쪽=최근)", "월 최고 재생", "최고 달"], trend), ""]
    lines += [f"- 라이브러리 전체 대비 월별 비중 추이: {_sparkline(pct)} (최고 {max(pct)}%, 최근 달 {pct[-1]}%)", ""]
    recent = months[-6:]
    lines += ["### 최근 6개월 월별 재생", _table(["항목"] + recent, [["선택 전체"] + _monthly(union, recent)] + [[label(it)] + _monthly(rows, recent) for it, rows in rows_by_item]), ""]

    # 항목별 상세
    lines.append("## 3. 항목별 상세")
    for it, rows in rows_by_item:
        lines.append(f"### {label(it)}")
        if rows.empty:
            lines += ["(이 기간에 기록이 없습니다)", ""]
            continue
        if it["kind"] == "artist":
            tags = _tags(it["name"])
            if tags:
                lines.append(f"- 태그(Last.fm 캐시): {', '.join(tags)}")
            albums = _top(rows, "album", 5)
            if albums:
                lines += ["- 많이 들은 앨범: " + ", ".join(f"{n}({c})" for n, c in albums)]
        tracks = _top(rows, "track", 10)
        lines.append("- 많이 들은 곡: " + (", ".join(f"{n}({c})" for n, c in tracks) if tracks else "(없음)"))
        distinct_tracks = len({k for k in resolve_all(rows, "track")[0] if k})
        lines.append(f"- 들은 곡 종류: {distinct_tracks}곡 · 들은 날 {_kst(rows).dt.strftime('%Y-%m-%d').nunique()}일")
        lines.append("")

    # 합집합의 시간 패턴
    lines.append("## 4. 선택 항목을 듣는 시간 패턴 (한국 시간)")
    wd = kst_sel.dt.dayofweek.value_counts().reindex(range(7), fill_value=0)
    lines.append(_table(["요일", *WEEKDAYS], [["재생", *[int(v) for v in wd.values]]]))
    hr = kst_sel.dt.hour.value_counts().reindex(range(24), fill_value=0)
    peak = hr.sort_values(ascending=False).head(3)
    lines.append(f"- 시간대별 재생(0~23시): {_sparkline([int(v) for v in hr.values])}")
    lines.append("- 가장 많이 듣는 시간대: " + ", ".join(f"{int(h)}시({int(c)}회)" for h, c in peak.items()))
    lines.append("")

    # 합집합 Top 곡 / 겹치는 항목
    lines.append("## 5. 선택 전체에서 많이 들은 곡 Top 10")
    top_tracks = _top(union, "track", 10)
    lines += [_table(["순위", "곡", "재생"], [[i, n, c] for i, (n, c) in enumerate(top_tracks, 1)]), ""]

    lines += [
        "## 6. 분석 요청",
        "위 데이터만 근거로, (1) 이 선택 항목들을 제가 듣는 패턴(시기별 몰입과 식는 시기, 요일·시간대)과 (2) 항목들 사이의 공통점·차이, "
        "(3) 제 취향에서 이 항목들이 차지하는 위치, (4) 비슷한 결로 더 들어볼 만한 아티스트·앨범 추천을 정리해 주세요. 수치로 확인되지 않는 내용은 추측이라고 표시해 주세요.",
    ]
    return {"prompt": "\n".join(lines), "scrobbles": int(len(union))}
