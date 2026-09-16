import pandas as pd
from app.analysis.diversity import compute_diversity
from app.analysis.discovery import compute_discovery, get_discovery_timeline
from app.analysis.taste import compute_tag_distribution, compute_tag_evolution_dynamic
from app.analysis.trends import (
    compute_region_trend,
    compute_artist_delta_ranking,
    compute_tag_delta_ranking,
    compute_artist_churn,
    compute_binge_sessions,
    compute_recent_concentration,
)

_BLOCKS = "▁▂▃▄▅▆▇█"


def _sparkline(values: list[float]) -> str:
    max_v = max(values) if values else 0
    if max_v <= 0:
        return _BLOCKS[0] * len(values)
    idx = [min(int((v / max_v) * (len(_BLOCKS) - 1)), len(_BLOCKS) - 1) for v in values]
    return "".join(_BLOCKS[i] for i in idx)


def _table(headers: list[str], rows: list[list]) -> str:
    if not rows:
        return "(데이터 없음)"
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join(["---"] * len(headers)) + "|")
    for row in rows:
        lines.append("| " + " | ".join(str(c) for c in row) + " |")
    return "\n".join(lines)


def _top_n(df: pd.DataFrame, column: str, n: int = 10) -> list[tuple[str, int]]:
    valid = df[df[column].notna() & (df[column] != "")]
    counts = valid[column].value_counts().head(n)
    return list(counts.items())


def build_ai_prompt(df: pd.DataFrame) -> str:
    df = df.copy()
    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True, format="mixed")
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")

    total_scrobbles = len(df)
    unique_artists = df["artist"].nunique()
    unique_tracks = df["track"].nunique()
    unique_albums = df["album"].nunique()
    first_date = df["datetime_kst"].min().strftime("%Y-%m-%d")
    last_date = df["datetime_kst"].max().strftime("%Y-%m-%d")

    top_artists = _top_n(df, "artist", 10)
    top_tracks = _top_n(df, "track", 10)
    top_albums = _top_n(df, "album", 10)

    diversity = compute_diversity(df)
    discovery = compute_discovery(df)
    tag_dist = compute_tag_distribution(df, top_n=10)
    tag_evolution = compute_tag_evolution_dynamic(df, top_n_tags=5)
    discovery_timeline = get_discovery_timeline(df, category="track", limit=10)

    region_trend = compute_region_trend(df, recent_months=3)
    artist_delta = compute_artist_delta_ranking(df, recent_weeks=4, top_n=10)
    tag_delta = compute_tag_delta_ranking(df, recent_weeks=4, top_n=10)
    churn = compute_artist_churn(df, recent_weeks=4, top_n=10)
    binge = compute_binge_sessions(df, gap_minutes=10, min_session_length=3)
    recent_focus = compute_recent_concentration(df, days=30, top_n=10)

    weekday_counts = df["datetime_kst"].dt.dayofweek.value_counts().sort_index()
    weekday_labels = ["월", "화", "수", "목", "금", "토", "일"]

    hourly_counts = df["datetime_kst"].dt.hour.value_counts().reindex(range(24), fill_value=0)

    monthly_counts = df.groupby(df["datetime_kst"].dt.strftime("%Y-%m")).size().sort_index()

    lines = []
    lines.append(
        "당신은 음악 청취 데이터를 분석하는 전문가입니다. 아래는 제 Last.fm 청취 기록을 정리한 "
        "수치 데이터입니다 (해석은 최소화하고 계산된 수치/표 위주로 정리했습니다). 이 데이터를 "
        "바탕으로 분석해 주세요.\n"
    )

    # 1. 기본 통계
    lines.append("## 1. 기본 통계")
    lines.append(f"- 데이터 기간: {first_date} ~ {last_date}")
    lines.append(f"- 총 스크로블 수: {total_scrobbles:,}회")
    lines.append(f"- 고유 아티스트 수: {unique_artists}명")
    lines.append(f"- 고유 트랙 수: {unique_tracks}개")
    lines.append(f"- 고유 앨범 수: {unique_albums}개")
    lines.append("")

    # 2. 순위
    lines.append("## 2. 순위 (재생 횟수 기준)")
    lines.append("### Top 10 아티스트")
    lines.append(_table(["순위", "아티스트", "재생 횟수"], [[i, n, c] for i, (n, c) in enumerate(top_artists, 1)]))
    lines.append("")
    lines.append("### Top 10 트랙")
    lines.append(_table(["순위", "트랙", "재생 횟수"], [[i, n, c] for i, (n, c) in enumerate(top_tracks, 1)]))
    lines.append("")
    lines.append("### Top 10 앨범")
    lines.append(_table(["순위", "앨범", "재생 횟수"], [[i, n, c] for i, (n, c) in enumerate(top_albums, 1)]))
    lines.append("")

    # 3. 언어/지역권 트렌드
    lines.append("## 3. 언어/지역권 트렌드")
    lines.append(
        "(아티스트명의 Last.fm 태그(japanese/korean 등)를 우선 사용하고, 태그가 없는 경우 "
        "문자 체계(한글/가나/한자/라틴)로 보완 분류. 로마자 표기 아티스트는 태그가 없으면 "
        "'영어권'으로 잡힐 수 있어 실제보다 과소 추정될 수 있음)"
    )
    lines.append("")
    lines.append("### 월별 권역 재생 비중(%) 추이")
    region_rows = []
    for region in region_trend["regions"]:
        pct_values = region_trend["monthly_pct"][region]
        region_rows.append([region, _sparkline(pct_values), f"{pct_values[-1]}%" if pct_values else "-"])
    lines.append(_table(["권역", "추이(왼쪽=과거 → 오른쪽=최근)", "최신월 비중"], region_rows))
    lines.append(f"기간: {region_trend['periods'][0]} ~ {region_trend['periods'][-1]}")
    lines.append("")
    lines.append(f"### 최근 {len(region_trend['recent_months'])}개월 평균 vs 그 이전 평균 비교")
    delta_rows = [
        [
            region,
            f"{region_trend['prior_avg_pct'].get(region, 0)}%",
            f"{region_trend['recent_avg_pct'].get(region, 0)}%",
            f"{region_trend['delta_pp'].get(region, 0):+.1f}%p",
        ]
        for region in region_trend["regions"]
    ]
    lines.append(_table(["권역", "이전 평균", "최근 평균", "증감"], delta_rows))
    lines.append("")

    # 4. 장르/태그
    lines.append(
        f"## 4. 장르/태그 (Last.fm 기준, {tag_dist['covered_artists']}/"
        f"{tag_dist['total_artists']} 아티스트 데이터 반영)"
    )
    if tag_dist.get("tags"):
        lines.append("### 선호 장르 Top 10 (누적 가중치)")
        lines.append(
            _table(
                ["순위", "태그", "가중치 점수"],
                [[i, t["tag"], t["score"]] for i, t in enumerate(tag_dist["tags"], 1)],
            )
        )
        lines.append("")

        if tag_evolution.get("series"):
            lines.append("### 월별 실제 선호 장르 순위 변화 (그 달의 진짜 Top 5 태그, 값 없으면 그 달은 Top 5 밖)")
            periods = tag_evolution["periods"]
            header = ["태그"] + periods
            rows = [
                [s["tag"]] + [(v if v is not None else "-") for v in s["values"]]
                for s in tag_evolution["series"]
            ]
            lines.append(_table(header, rows))
            lines.append("")
    else:
        lines.append("(태그 캐시 없음 — Taste 탭에서 아티스트 태그를 먼저 조회해야 이 항목이 채워집니다.)")
        lines.append("")

    # 5. 급상승/급하락 (Delta 랭킹)
    lines.append(
        f"## 5. 급상승/급하락 (최근 {artist_delta['recent_weeks']}주: "
        f"{artist_delta['recent_range'][0]} ~ {artist_delta['recent_range'][1]} "
        f"vs 그 이전 {artist_delta['recent_weeks']}주: "
        f"{artist_delta['prior_range'][0]} ~ {artist_delta['prior_range'][1]})"
    )
    lines.append("### 아티스트 급상승 Top 10")
    lines.append(
        _table(
            ["아티스트", "이전 재생", "최근 재생", "증감"],
            [[d["name"], d["prior"], d["recent"], f"{d['delta']:+d}"] for d in artist_delta["top_gainers"]],
        )
    )
    lines.append("")
    lines.append("### 아티스트 급하락 Top 10")
    lines.append(
        _table(
            ["아티스트", "이전 재생", "최근 재생", "증감"],
            [[d["name"], d["prior"], d["recent"], f"{d['delta']:+d}"] for d in artist_delta["top_decliners"]],
        )
    )
    lines.append("")
    lines.append("### 장르 급상승 Top 10 (가중치 기준)")
    lines.append(
        _table(
            ["태그", "이전 가중치", "최근 가중치", "증감"],
            [[d["name"], d["prior"], d["recent"], f"{d['delta']:+.1f}"] for d in tag_delta["top_gainers"]],
        )
    )
    lines.append("")
    lines.append("### 장르 급하락 Top 10 (가중치 기준)")
    lines.append(
        _table(
            ["태그", "이전 가중치", "최근 가중치", "증감"],
            [[d["name"], d["prior"], d["recent"], f"{d['delta']:+.1f}"] for d in tag_delta["top_decliners"]],
        )
    )
    lines.append("")

    # 6. 이탈/재발견 아티스트
    lines.append(f"## 6. 이탈/재발견 아티스트 (기준: 최근 {churn['recent_weeks']}주)")
    lines.append(f"### 이탈 (그 이전엔 꾸준히 들었으나 최근 {churn['recent_weeks']}주간 재생 0회)")
    lines.append(
        _table(
            ["아티스트", "과거 누적 재생", "과거 주당 평균"],
            [[c["name"], c["history_plays"], c["history_weekly_avg"]] for c in churn["churned"]],
        )
    )
    lines.append("")
    lines.append("### 재발견 (과거 대비 최근 재생 빈도 급증, 배수 기준)")
    lines.append(
        _table(
            ["아티스트", "과거 누적 재생", "과거 주당 평균", "최근 재생", "배수"],
            [
                [c["name"], c["history_plays"], c["history_weekly_avg"], c["recent_plays"], f"x{c['surge_multiple']}"]
                for c in churn["rediscovered"]
            ],
        )
    )
    lines.append("")

    # 7. 소비 패턴
    lines.append("## 7. 소비 패턴")
    lines.append("### 다양성 지표")
    diversity_rows = []
    for key, label in [("artist", "아티스트"), ("track", "트랙"), ("album", "앨범")]:
        m = diversity[key]
        diversity_rows.append(
            [
                label,
                f"{round(m['normalized_entropy'] * 100)}/100",
                f"{m['top10pct_concentration']}%",
                f"{m['most_played']['name']} ({m['most_played']['count']}회)",
            ]
        )
    lines.append(_table(["구분", "다양성 점수", "상위 10% 집중도", "최다 재생"], diversity_rows))
    lines.append("")

    lines.append("### 탐색(Discovery) 지표")
    lines.append(f"- 전체 기간 신규 트랙 수: {discovery['track']['total_new']}개")
    lines.append(f"- 전체 기간 신규 아티스트 수: {discovery['artist']['total_new']}명")
    lines.append(f"- 전체 기간 신규 앨범 수: {discovery['album']['total_new']}개")
    lines.append("")

    lines.append("### 월별 청취량 추이")
    lines.append(f"추이: {_sparkline(list(monthly_counts.values))}  (왼쪽={monthly_counts.index[0]} → 오른쪽={monthly_counts.index[-1]})")
    lines.append(
        _table(["월", "재생 횟수"], [[p, int(c)] for p, c in monthly_counts.items()])
    )
    lines.append("")

    lines.append("### 요일별 청취 분포")
    lines.append(
        _table(
            ["요일", "재생 횟수"],
            [[weekday_labels[i], int(weekday_counts.get(i, 0))] for i in range(7)],
        )
    )
    lines.append("")

    lines.append("### 시간대별 청취 분포 (0~23시)")
    lines.append(f"추이: {_sparkline(list(hourly_counts.values))}  (왼쪽=0시 → 오른쪽=23시)")
    lines.append(
        _table(["시간대", "재생 횟수"], [[f"{h}시", int(hourly_counts.get(h, 0))] for h in range(24)])
    )
    lines.append("")

    # 8. 청취 강도 & 몰입 패턴
    lines.append(
        f"## 8. 청취 강도 & 몰입 패턴 (같은 아티스트를 {binge['gap_minutes']}분 이내 간격으로 "
        f"{binge['min_session_length']}곡 이상 연속 재생 = '몰아듣기 세션')"
    )
    lines.append(f"- 전체 몰아듣기 세션 수: {binge['total_sessions']}회")
    lines.append(f"추이: {_sparkline(binge['monthly_session_counts'])}  (왼쪽={binge['periods'][0] if binge['periods'] else '-'} → 오른쪽={binge['periods'][-1] if binge['periods'] else '-'})")
    lines.append("")
    lines.append("### 월별 몰아듣기 세션 빈도")
    lines.append(
        _table(
            ["월", "세션 수"],
            [[p, c] for p, c in zip(binge["periods"], binge["monthly_session_counts"])],
        )
    )
    lines.append("")
    lines.append("### 가장 길었던 몰아듣기 세션 Top 5 (참고용)")
    lines.append(
        _table(
            ["아티스트", "연속 재생 곡 수", "시작", "종료"],
            [[s["artist"], s["track_count"], s["start"], s["end"]] for s in binge["longest_sessions"][:5]],
        )
    )
    lines.append("")

    # 9. 신곡 vs 구곡 비율 (미포함 안내)
    lines.append("## 9. 신곡 vs 구곡 비율")
    lines.append("※ 트랙 발매연도 데이터를 보유하고 있지 않아 이 항목은 계산에서 제외했습니다.")
    lines.append("")

    # 10. 최근 트렌드
    lines.append("## 10. 최근 트렌드")
    if discovery_timeline:
        lines.append("### 최근에 새로 발견한 트랙 Top 10 (최신순)")
        rows = []
        for item in discovery_timeline:
            artist_part = item.get("artist") or "-"
            rows.append([item["name"], artist_part, item["first_listened"]])
        lines.append(_table(["트랙", "아티스트", "처음 청취일"], rows))
        lines.append("")

    lines.append(
        f"### 최근 {recent_focus['days']}일 내 재생 비중이 가장 큰 아티스트/장르 "
        "(절대 순위가 아닌 최근 구간 내 집중도 기준)"
    )
    lines.append(f"기간: {recent_focus['window_range'][0]} ~ {recent_focus['window_range'][1]}, 총 {recent_focus['window_total_plays']}회 재생")
    lines.append("#### 아티스트")
    lines.append(
        _table(
            ["아티스트", "재생 횟수", "구간 내 비중"],
            [[a["name"], a["plays"], f"{a['share_pct']}%"] for a in recent_focus["top_artists"]],
        )
    )
    lines.append("")
    lines.append("#### 장르")
    lines.append(
        _table(
            ["태그", "가중치 점수", "구간 내 비중"],
            [[t["name"], t["score"], f"{t['share_pct']}%"] for t in recent_focus["top_tags"]],
        )
    )
    lines.append("")

    lines.append("## 분석 요청")
    lines.append("위 데이터를 참고해서 다음을 알려주세요:")
    lines.append("1. 제 음악 취향을 한두 문단으로 요약해 주세요.")
    lines.append("2. 언어/지역권 트렌드와 급상승/급하락 랭킹을 보고, 최근 취향이 어느 방향으로 이동하고 있는지 짚어주세요.")
    lines.append("3. 이탈/재발견 아티스트 목록을 보고, 제 취향에 주기성이나 회귀 패턴이 있는지 분석해 주세요.")
    lines.append("4. 몰아듣기 세션 빈도 추이를 보고, 최근 청취 몰입도가 늘고 있는지 줄고 있는지 판단해 주세요.")
    lines.append("5. 최근 발견한 트랙과 최근 집중도 데이터를 참고해서, 제 취향과 결이 비슷하면서 아직 안 들어봤을 법한 아티스트를 3~5명 추천해 주세요.")
    lines.append("6. 제 음악 소비 방식(다양성, 집중도, 반복 재생 등)에 대한 솔직한 피드백이 있다면 말해주세요.")

    return "\n".join(lines)
