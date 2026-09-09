import math
import pandas as pd


def _shannon_entropy(counts: pd.Series) -> float:
    """
    Shannon entropy 계산. 값이 클수록 다양하게 골고루 들었다는 뜻,
    값이 작을수록 소수의 아티스트/트랙에 집중해서 들었다는 뜻.
    """
    total = counts.sum()
    if total == 0:
        return 0.0

    probabilities = counts / total
    entropy = -sum(p * math.log2(p) for p in probabilities if p > 0)
    return round(entropy, 3)


def _concentration_ratio(counts: pd.Series, top_pct: float = 0.1) -> float:
    """
    상위 top_pct(예: 10%) 항목이 전체 재생 횟수의 몇 %를 차지하는지.
    값이 높을수록 소수에 집중된 청취 패턴.
    """
    total = counts.sum()
    if total == 0 or len(counts) == 0:
        return 0.0

    n_top = max(1, int(len(counts) * top_pct))
    top_sum = counts.sort_values(ascending=False).head(n_top).sum()
    return round((top_sum / total) * 100, 1)


def compute_diversity(df: pd.DataFrame) -> dict:
    result = {}

    for category, column in [("artist", "artist"), ("track", "track"), ("album", "album")]:
        valid = df[df[column].notna() & (df[column] != "")]
        counts = valid[column].value_counts()

        max_entropy = math.log2(len(counts)) if len(counts) > 1 else 1
        entropy = _shannon_entropy(counts)
        normalized_entropy = round(entropy / max_entropy, 3) if max_entropy > 0 else 0

        result[category] = {
            "unique_count": len(counts),
            "entropy": entropy,
            "normalized_entropy": normalized_entropy,  # 0~1, 1에 가까울수록 매우 다양
            "top10pct_concentration": _concentration_ratio(counts, 0.1),
            "most_played": {
                "name": counts.index[0] if len(counts) > 0 else None,
                "count": int(counts.iloc[0]) if len(counts) > 0 else 0,
            },
        }

    return result