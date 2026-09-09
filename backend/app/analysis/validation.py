import pandas as pd

REQUIRED_COLUMNS = ["uts", "utc_time", "artist", "album", "track"]


def validate_csv(df: pd.DataFrame) -> dict:
    """
    CSV 데이터프레임을 검증하고 문제점을 리스트로 반환한다.
    errors: 치명적 문제 (분석 진행 불가)
    warnings: 경고성 문제 (진행은 가능하나 사용자에게 알려야 함)
    """
    errors = []
    warnings = []

    # 1. 필수 컬럼 존재 여부
    missing_cols = [col for col in REQUIRED_COLUMNS if col not in df.columns]
    if missing_cols:
        errors.append(f"필수 컬럼 누락: {missing_cols}")
        # 컬럼 자체가 없으면 이후 검증은 의미 없으니 여기서 리턴
        return {"valid": False, "errors": errors, "warnings": warnings}

    # 2. uts 값의 유효성 (숫자로 변환 가능한지, 음수/0 아닌지)
    invalid_uts_count = 0
    for val in df["uts"]:
        try:
            uts_val = int(val)
            if uts_val <= 0:
                invalid_uts_count += 1
        except (ValueError, TypeError):
            invalid_uts_count += 1
    if invalid_uts_count > 0:
        warnings.append(f"유효하지 않은 uts 값: {invalid_uts_count}개")

    # 3. utc_time 형식의 유효성 (파싱 가능한지)
    parsed = pd.to_datetime(df["utc_time"], errors="coerce")
    invalid_time_count = parsed.isna().sum()
    if invalid_time_count > 0:
        warnings.append(f"파싱 불가능한 utc_time: {invalid_time_count}개")

    # 4. 빈 artist / album / track
    for col in ["artist", "album", "track"]:
        empty_count = df[col].isna().sum() + (df[col] == "").sum()
        if empty_count > 0:
            warnings.append(f"빈 {col} 값: {empty_count}개")

    # 5. 비정상적인 timestamp (미래 시각, 혹은 2002년 이전 - Last.fm 서비스 시작 전)
    now_uts = int(pd.Timestamp.now(tz="UTC").timestamp())
    lastfm_launch_uts = 1000000000  # 2001년 9월 대략
    try:
        uts_numeric = pd.to_numeric(df["uts"], errors="coerce")
        future_count = (uts_numeric > now_uts).sum()
        too_old_count = (uts_numeric < lastfm_launch_uts).sum()
        if future_count > 0:
            warnings.append(f"미래 시각으로 기록된 데이터: {future_count}개")
        if too_old_count > 0:
            warnings.append(f"비정상적으로 오래된 timestamp: {too_old_count}개")
    except Exception:
        pass

    # 6. 중복 데이터 (uts + artist + track 기준)
    dup_count = df.duplicated(subset=["uts", "artist", "track"]).sum()
    if dup_count > 0:
        warnings.append(f"중복된 스크롭 데이터: {dup_count}개")

    # 7. 전체 행 수가 0인 경우
    if len(df) == 0:
        errors.append("데이터가 비어 있습니다.")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "total_rows": len(df),
    }