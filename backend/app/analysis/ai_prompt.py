import pandas as pd
from app.analysis.diversity import compute_diversity
from app.analysis.keys import key_series, unique_count
from app.analysis.library import ranked_page
from app.analysis.listening_time import fmt_hm, time_summary
from app.analysis.discovery import compute_discovery, get_discovery_timeline
from app.analysis.taste import compute_tag_distribution, compute_tag_evolution_dynamic
from app.analysis.trends import (
    compute_region_trend,
    compute_artist_delta_ranking,
    compute_tag_delta_ranking,
    compute_artist_churn,
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
    unique_tracks = unique_count(df, "track")
    unique_albums = unique_count(df, "album")
    first_date = df["datetime_kst"].min().strftime("%Y-%m-%d")
    last_date = df["datetime_kst"].max().strftime("%Y-%m-%d")

    top_artists = _top_n(df, "artist", 10)
    # 곡명·앨범명만 같은 다른 아티스트의 항목(Untitled 등)이 합쳐지지 않도록 "아티스트 - 이름"으로 센다
    keyed = df.assign(track_key=key_series(df, "track"), album_key=key_series(df, "album"))
    top_tracks = _top_n(keyed, "track_key", 10)
    top_albums = _top_n(keyed, "album_key", 10)

    diversity = compute_diversity(df)
    discovery = compute_discovery(df)
    tag_dist = compute_tag_distribution(df, top_n=10)
    tag_evolution = compute_tag_evolution_dynamic(df, top_n_tags=5)
    discovery_timeline = get_discovery_timeline(df, category="track", limit=10)

    region_trend = compute_region_trend(df, recent_months=3)
    artist_delta = compute_artist_delta_ranking(df, recent_weeks=4, top_n=10)
    tag_delta = compute_tag_delta_ranking(df, recent_weeks=4, top_n=10)
    churn = compute_artist_churn(df, recent_weeks=4, top_n=10)
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
    ts = time_summary(df)
    busiest = ts["busiest_day"]
    lines.append(f"- 총 청취 시간(추정): {fmt_hm(ts['total_seconds'])} (곡 길이를 아는 재생 {ts['coverage'] * 100:.0f}% 기준, "
                 f"스크로블 횟수 x 곡 길이라 끝까지 들었다고 가정한 상한)")
    lines.append(f"- 하루 평균 청취 시간: {fmt_hm(ts['avg_seconds_per_day'])} (기간 {ts['days']}일 기준) · "
                 f"청취한 날 평균 {fmt_hm(ts['avg_seconds_per_active_day'])}")
    if busiest:
        lines.append(f"- 가장 많이 들은 날: {busiest['date']} ({fmt_hm(busiest['seconds'])}, {busiest['plays']}회)")
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

    # 2-2. 청취 시간 기준 순위 (횟수 순위와 다를 수 있다: 긴 곡·긴 앨범이 위로 올라온다)
    lines.append("## 2-2. 청취 시간 기준 순위")
    for cat, name in [("artist", "아티스트"), ("track", "트랙"), ("album", "앨범")]:
        page = ranked_page(df, cat, 0, 10, "time")["items"]
        item_name = lambda it: f"{it['artist']} - {it['name']}" if it.get("artist") and cat != "artist" else it["name"]  # noqa: E731
        lines.append(f"### Top 10 {name} (청취 시간순)")
        lines.append(_table(["순위", name, "청취 시간", "재생 횟수"], [[i, item_name(it), fmt_hm(it["seconds"]), it["count"]] for i, it in enumerate(page, 1)]))
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

    # 8. 신곡 vs 구곡 비율 (미포함 안내)
    lines.append("## 8. 신곡 vs 구곡 비율")
    lines.append("※ 트랙 발매연도 데이터를 보유하고 있지 않아 이 항목은 계산에서 제외했습니다.")
    lines.append("")

    # 10. 최근 트렌드
    lines.append("## 9. 최근 트렌드")
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

    lines.extend(analysis_request("all"))

    return "\n".join(lines)


def analysis_request(kind: str = "all", label: str | None = None, prev_label: str | None = None) -> list[str]:
    """
    프롬프트 맨 끝 "분석 요청" 블록. 원칙(근거 인용 · 불확실 분류 · 3단 구성 · 추측 금지)과 A~E 구조는 모든 프롬프트가 같고,
    kind(all / month / year / week)에 따라 B·C 가 가리키는 표와 추천 개수만 다르다. 이 블록은 프롬프트에 실제로 있는 섹션만 인용한다.
    """
    period = kind != "all"
    where = f"{label}" if label else "이 기간"
    vs = f"{prev_label}" if prev_label else "직전 기간"
    out = [
        "## 분석 요청",
        "위 데이터는 규칙 기반으로 미리 계산된 수치입니다. 아래 원칙을 지켜 분석해 주세요.",
        "",
        "[원칙]",
        "1. 모든 주장은 표/수치를 근거로 인용하세요 (예: \"점유 +9.3pp\", \"재생 245회\").",
        "2. 기록이 일부 기간만 있다고 표시된 경우, 태그가 반영된 아티스트 비율이 낮은 경우, 표본이 작은 구간은 취향 변화로 단정하지 말고 \"불확실\"로 분류하세요.",
        "3. 각 결론을 [관찰(수치) / 해석 / 다른 해석 가능성] 3단으로 나눠 쓰세요.",
        "4. 데이터에 없는 사실(발매연도, 멤버, 가사 내용, 데이터에 없는 앨범명)은 추측하지 말고, 모르면 모른다고 쓰세요.",
        "",
        "[요청]",
    ]
    if kind == "week":
        out.append(f"A. 요약: {where} 한 주의 청취를 5줄 이내로 요약하고, 가장 특징적인 점 1개를 강조하세요. 요일별 표를 근거로 하루하루의 특징을 짧게 짚어도 좋습니다.")
    elif period:
        out.append(f"A. 취향 요약: {where}의 취향을 5줄 이내로 요약하고, {vs}과 달라진 점 중 가장 특징적인 것 1개를 강조하세요.")
    else:
        out.append("A. 취향 요약: 상위 아티스트·장르를 근거로 5줄 이내로 요약하고, 가장 특징적인 점 1개를 강조하세요.")
    if period:
        out.append(f"B. 이동 방향: 순위 표의 '신규/복귀' 표시, 신규 발견 목록, 장르·언어권 비중 변화를 근거로 {vs} 대비 취향이 \"새 방향인지, 과거 회귀인지, 일시적 버스트인지\" 판정하고 확신도(높음/중간/낮음)를 붙이세요.")
        out.append("C. 청취 습관 진단: 청취량 흐름(몰아 들은 시기와 뜸했던 시기)과 시간대·세션 데이터를 근거로 강점 1개, 개선점 1개를 말해 주세요. 새벽 장시간 재생은 자는 동안 켜져 있던 것일 수 있으니 감안하세요.")
    else:
        out.append("B. 최근 이동 방향: 급상승/급하락, 이탈/재발견, 최근 집중도, 언어/지역권 추이를 근거로 \"새 방향인지, 과거 회귀인지, 일시적 버스트인지\" 판정하고 확신도(높음/중간/낮음)를 붙이세요.")
        out.append("C. 소비 방식 진단: 다양성·탐색(Discovery) 지표, 반복 재생, 월별·요일별·시간대별 분포를 근거로 청취 습관의 강점 1개, 개선점 1개를 말해 주세요.")
    n = {"month": "3~5명", "year": "5명", "week": "2~3명"}.get(kind, "3~5명")
    out.append(
        f"D. 비슷한 결의 아티스트 {n} 추천: 이 프롬프트에 등장한 아티스트는 제외하세요. 각 추천마다 ① 어떤 수치(장르·집중도 등)와 연결되는지 1문장, "
        "② 어울리지 않을 수 있는 이유 1문장, ③ 처음 들어볼 곡이나 앨범은 확실히 알 때만 적으세요."
    )
    out.append("E. 추가로 있으면 분석이 더 정확해질 데이터 3가지를 제안하세요.")
    out.append("")
    out.append("답변은 A~E 순서로 써 주세요.")
    return out
