import pandas as pd


def filter_by_date_range(df: pd.DataFrame, start: str | None, end: str | None) -> pd.DataFrame:
    """
    start, end: 'YYYY-MM-DD' 형식 문자열 (한국 시간 기준).
    둘 다 없으면 원본 그대로 반환한다.
    """
    if not start and not end:
        return df

    df = df.copy()
    df["datetime_utc"] = pd.to_datetime(df["utc_time"], utc=True)
    df["datetime_kst"] = df["datetime_utc"].dt.tz_convert("Asia/Seoul")

    if start:
        start_ts = pd.Timestamp(start, tz="Asia/Seoul")
        df = df[df["datetime_kst"] >= start_ts]

    if end:
        # end 날짜의 끝(자정 직전)까지 포함
        end_ts = pd.Timestamp(end, tz="Asia/Seoul") + pd.Timedelta(days=1)
        df = df[df["datetime_kst"] < end_ts]

    return df