import pandas as pd


def key_series(df: pd.DataFrame, column: str) -> pd.Series:
    """
    집계용 키. 곡명·앨범명만 같은 다른 아티스트의 항목(Untitled, Eureka, Romance 등)이
    한 항목으로 합쳐지지 않도록 트랙/앨범은 "아티스트 - 이름"으로 만든다.
    아티스트 열이면 그대로, 이름이 비어 있으면 "" (집계에서 제외할 값)을 돌려준다.
    """
    name = df[column].fillna("").astype(str)
    if column == "artist":
        return name
    artist = df["artist"].fillna("").astype(str)
    key = (artist + " - " + name).where(artist != "", name)
    return key.where(name != "", "")


def unique_count(df: pd.DataFrame, column: str) -> int:
    keys = key_series(df, column)
    return int(keys[keys != ""].nunique())
