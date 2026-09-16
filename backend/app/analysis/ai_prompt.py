import pandas as pd
from app.analysis.diversity import compute_diversity
from app.analysis.discovery import compute_discovery, get_discovery_timeline
from app.analysis.taste import compute_tag_distribution, compute_tag_evolution_dynamic


def _top_n(df: pd.DataFrame, column: str, n: int = 10) -> list[tuple[str, int]]:
    valid = df[df[column].notna() & (df[column] != "")]
    counts = valid[column].value_counts().head(n)
    return list(counts.items())


def build_ai_prompt(df: pd.DataFrame) -> str:
    df = df.copy()
    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True)
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

    weekday_counts = df["datetime_kst"].dt.dayofweek.value_counts().sort_index()
    weekday_labels = ["월", "화", "수", "목", "금", "토", "일"]

    monthly_counts = df.groupby(df["datetime_kst"].dt.strftime("%Y-%m")).size().sort_index()

    lines = []
    lines.append(
        "당신은 음악 청취 데이터를 분석하는 전문가입니다. 아래는 제 Last.fm 청취 기록을 정리한 "
        "데이터입니다. 이 데이터를 바탕으로 제 음악 취향의 특징, 시간에 따른 변화, 흥미로운 "
        "패턴을 분석해 주세요.\n"
    )

    lines.append("## 기본 정보")
    lines.append(f"- 데이터 기간: {first_date} ~ {last_date}")
    lines.append(f"- 총 스크로블 수: {total_scrobbles:,}회")
    lines.append(f"- 고유 아티스트 수: {unique_artists}명")
    lines.append(f"- 고유 트랙 수: {unique_tracks}개")
    lines.append(f"- 고유 앨범 수: {unique_albums}개")
    lines.append("")

    lines.append("## Top 10 아티스트 (재생 횟수)")
    for i, (name, count) in enumerate(top_artists, 1):
        lines.append(f"{i}. {name} - {count}회")
    lines.append("")

    lines.append("## Top 10 트랙 (재생 횟수)")
    for i, (name, count) in enumerate(top_tracks, 1):
        lines.append(f"{i}. {name} - {count}회")
    lines.append("")

    lines.append("## Top 10 앨범 (재생 횟수)")
    for i, (name, count) in enumerate(top_albums, 1):
        lines.append(f"{i}. {name} - {count}회")
    lines.append("")

    if tag_dist.get("tags"):
        lines.append(
            f"## 선호 장르/태그 (Last.fm 기준, {tag_dist['covered_artists']}/"
            f"{tag_dist['total_artists']} 아티스트 데이터 반영)"
        )
        for t in tag_dist["tags"]:
            lines.append(f"- {t['tag']}: 가중치 {t['score']}")
        lines.append("")

    lines.append("## 음악 소비 다양성 지표")
    for key, label in [("artist", "아티스트"), ("track", "트랙"), ("album", "앨범")]:
        m = diversity[key]
        lines.append(
            f"- {label}: 다양성 점수 {round(m['normalized_entropy'] * 100)}/100, "
            f"상위 10%가 전체의 {m['top10pct_concentration']}% 차지, "
            f"가장 많이 들은 {label}은 '{m['most_played']['name']}' ({m['most_played']['count']}회)"
        )
    lines.append("")

    lines.append("## 음악 탐색(Discovery) 지표")
    lines.append(f"- 전체 기간 신규 트랙 수: {discovery['track']['total_new']}개")
    lines.append(f"- 전체 기간 신규 아티스트 수: {discovery['artist']['total_new']}명")
    lines.append(f"- 전체 기간 신규 앨범 수: {discovery['album']['total_new']}개")
    lines.append("")

    lines.append("## 월별 청취량 추이")
    for period, count in monthly_counts.items():
        lines.append(f"- {period}: {count}회")
    lines.append("")

    lines.append("## 요일별 청취 분포")
    for i, label in enumerate(weekday_labels):
        count = int(weekday_counts.get(i, 0))
        lines.append(f"- {label}요일: {count}회")
    lines.append("")

    if tag_evolution.get("series"):
        lines.append("## 월별 실제 선호 장르 순위 변화 (그 달의 진짜 Top 5 태그, 값이 없으면 그 달엔 Top 5 밖)")
        lines.append(f"기간: {', '.join(tag_evolution['periods'])}")
        for s in tag_evolution["series"]:
            values_str = ", ".join(
                f"{p}: {v if v is not None else '순위밖'}"
                for p, v in zip(tag_evolution["periods"], s["values"])
            )
            lines.append(f"- {s['tag']}: {values_str}")
        lines.append("")

    if discovery_timeline:
        lines.append("## 최근에 새로 발견한 트랙 (최신순)")
        for item in discovery_timeline:
            artist_part = f" - {item['artist']}" if item.get("artist") else ""
            lines.append(f"- {item['name']}{artist_part} (처음 청취: {item['first_listened']})")
        lines.append("")

    lines.append("## 분석 요청")
    lines.append("위 데이터를 참고해서 다음을 알려주세요:")
    lines.append("1. 제 음악 취향을 한두 문단으로 요약해 주세요.")
    lines.append("2. 월별 추이와 요일별 분포를 보고, 제 청취 습관에서 발견되는 특징이 있다면 짚어주세요.")
    lines.append("3. 월별 장르 순위 변화를 보고, 제 취향이 시간에 따라 어떻게 바뀌었는지 분석해 주세요.")
    lines.append("4. 최근 발견한 트랙들을 참고해서, 제 취향과 결이 비슷하면서 아직 안 들어봤을 법한 아티스트를 3~5명 추천해 주세요.")
    lines.append("5. 제 음악 소비 방식(다양성, 집중도, 반복 재생 등)에 대한 솔직한 피드백이 있다면 말해주세요.")

    return "\n".join(lines)