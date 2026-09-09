import pandas as pd


def compute_discovery(df: pd.DataFrame) -> dict:
    """
    트랙/아티스트/앨범 각각의 최초 청취 시점을 찾고,
    월별 신규 발견 개수를 계산한다.
    """
    df = df.copy()
    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True)
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")
    df["year_month"] = df["datetime_kst"].dt.strftime("%Y-%m")

    df_sorted = df.sort_values("datetime_kst")

    result = {}
    for category, column in [("track", "track"), ("artist", "artist"), ("album", "album")]:
        valid = df_sorted[df_sorted[column].notna() & (df_sorted[column] != "")]
        first_seen = valid.drop_duplicates(subset=[column], keep="first")

        monthly_new = first_seen.groupby("year_month").size().sort_index()

        result[category] = {
            "total_new": len(first_seen),
            "months": monthly_new.index.tolist(),
            "counts": monthly_new.values.tolist(),
        }

    return result


def get_discovery_timeline(df: pd.DataFrame, category: str = "track", limit: int = 50) -> list[dict]:
    """
    최근에 새로 발견한 순서대로 항목 목록을 반환한다 (타임라인용).
    """
    column_map = {"track": "track", "artist": "artist", "album": "album"}
    column = column_map.get(category, "track")

    df = df.copy()
    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True)
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")

    df_sorted = df.sort_values("datetime_kst")
    valid = df_sorted[df_sorted[column].notna() & (df_sorted[column] != "")]
    first_seen = valid.drop_duplicates(subset=[column], keep="first")

    first_seen = first_seen.sort_values("datetime_kst", ascending=False).head(limit)

    results = []
    for _, row in first_seen.iterrows():
        results.append(
            {
                "name": row[column],
                "artist": row["artist"] if column != "artist" else None,
                "first_listened": row["datetime_kst"].strftime("%Y-%m-%d %H:%M"),
            }
        )

    return results