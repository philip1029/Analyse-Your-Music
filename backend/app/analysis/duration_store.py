from pathlib import Path

from app.lastfm.durations import CACHE_NAME, DurationLookup

# data/track_durations.json (scripts/fill_durations.py 가 채움). 없으면 길이는 모두 None.
durations = DurationLookup(Path(__file__).resolve().parents[3] / "data" / CACHE_NAME)
