"""Overview "Did you know?" 후보 생성 규칙 테스트 (합성 데이터). 생성기를 하나씩 직접 불러서, build_facts 가 삼키는 오류도 여기서 드러나게 한다. 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.analysis import fun_facts as ff  # noqa: E402

TODAY = date(2026, 10, 22)


def uts(ts: str) -> int:
    return int(pd.Timestamp(ts, tz="Asia/Seoul").timestamp())


def mk(rows) -> pd.DataFrame:
    """rows: [(KST 시각 'YYYY-MM-DD HH:MM:SS', 아티스트, 앨범, 곡)]"""
    return pd.DataFrame([{"uts": uts(t), "utc_time": "", "artist": a, "album": al, "track": tr, "source": "L"} for t, a, al, tr in rows])


def ctx(rows, words=("night",), today=TODAY) -> ff._Ctx:
    return ff._Ctx(mk(rows), today, list(words))


def day_rows(day: str, n: int, artist="A", album="Al", track="T{i}", start_hour=10, step_min=3):
    """하루에 n곡 (곡명에 {i} 를 쓰면 번호가 들어간다)."""
    base = pd.Timestamp(f"{day} {start_hour:02d}:00:00")
    return [((base + pd.Timedelta(minutes=i * step_min)).strftime("%Y-%m-%d %H:%M:%S"), artist, album, track.format(i=i)) for i in range(n)]


def texts(facts):
    return [f["text"] for f in facts]


class BuildFactsTest(unittest.TestCase):
    def test_empty_and_missing_columns(self):
        self.assertEqual(ff.build_facts(pd.DataFrame()), [])
        self.assertEqual(ff.build_facts(pd.DataFrame({"uts": [1], "artist": ["a"]})), [])
        self.assertEqual(ff.build_facts(None), [])

    def test_blank_tracks_only(self):
        self.assertEqual(ff.build_facts(mk([("2025-01-01 10:00:00", "", "", "")]), TODAY), [])

    def test_one_failing_generator_does_not_hide_the_rest(self):
        def boom(c):
            raise RuntimeError("x")

        df = mk(day_rows("2025-01-01", 3))
        with mock.patch.object(ff, "GENERATORS", [boom, ff._first_ever]):
            out = ff.build_facts(df, TODAY, [])
        self.assertEqual([f["group"] for f in out], ["first_ever"])

    def test_every_generator_runs_on_a_tiny_dataset(self):
        c = ctx(day_rows("2025-01-01", 3))
        for gen in ff.GENERATORS:
            self.assertIsInstance(gen(c), list, gen.__name__)          # 오류 없이 (대부분 빈) 목록

    def test_ids_are_unique_and_shaped(self):
        rows = day_rows("2024-06-02", 30) + day_rows("2025-03-01", 40, artist="B", album="B", track="x{i}")
        facts = ff.build_facts(mk(rows), TODAY, ["x"])
        self.assertEqual(len({f["id"] for f in facts}), len(facts))
        for f in facts:
            self.assertEqual(set(f), {"id", "group", "icon", "text"})
            self.assertTrue(f["text"])


class FirstAndAnniversaryTest(unittest.TestCase):
    def test_first_ever_and_first_this_year(self):
        c = ctx([("2024-06-02 10:00:00", "Tom Petty", "Al", "Free Fallin'"), ("2026-01-01 09:00:00", "Pharoah", "Al", "Plan"), ("2026-03-01 09:00:00", "Z", "Al", "Z")])
        self.assertIn("가장 처음 기록된 스크로블은 Tom Petty의 ‘Free Fallin'’ 곡이에요 (2024년 6월 2일)", ff._first_ever(c)[0]["text"])
        self.assertIn("올해 첫 스크로블은 Pharoah의 ‘Plan’", ff._first_this_year(c)[0]["text"])

    def test_first_this_year_skipped_when_it_is_the_first_ever(self):
        c = ctx([("2026-02-01 10:00:00", "A", "Al", "T"), ("2026-03-01 10:00:00", "A", "Al", "U")])
        self.assertEqual(ff._first_this_year(c), [])

    def test_on_this_day(self):
        rows = [("2024-10-22 10:00:00", "Pink Floyd", "Al", "Echoes"), ("2024-10-22 11:00:00", "Pink Floyd", "Al", "Echoes"), ("2024-10-22 12:00:00", "B", "Al", "Other"), ("2026-10-21 10:00:00", "A", "Al", "T")]
        out = ff._on_this_day(ctx(rows))
        self.assertIn("2년 전 오늘(2024년 10월 22일)은 Pink Floyd의 ‘Echoes’ 등 3곡을 들었어요", out[0]["text"])

    def test_on_this_day_single_track_and_none(self):
        single = ff._on_this_day(ctx([("2025-10-22 10:00:00", "A", "Al", "Only")]))
        self.assertIn("1년 전 오늘", single[0]["text"])
        self.assertIn("한 곡을", single[0]["text"])
        self.assertEqual(ff._on_this_day(ctx([("2025-10-21 10:00:00", "A", "Al", "T")])), [])
        self.assertEqual(ff._on_this_day(ctx([("2026-10-22 10:00:00", "A", "Al", "T")])), [])            # 올해 오늘은 제외

    def test_milestones(self):
        rows = [(f"2025-01-01 {i // 60:02d}:{i % 60:02d}:00", "A", "Al", f"T{i}") for i in range(1000)]
        out = ff._milestones(ctx(rows))
        self.assertEqual([f["id"] for f in out], ["milestone:1000"])
        self.assertIn("1,000번째 스크로블은 A의 ‘T999’", out[0]["text"])
        self.assertEqual(ff._milestones(ctx(rows[:999])), [])


class TitleFactsTest(unittest.TestCase):
    def tracks(self, titles, artist="A"):
        return [(f"2025-01-{1 + i // 20:02d} 10:{(i % 20) * 3:02d}:00", artist, "Al", t) for i, t in enumerate(titles)]

    def test_title_word_boundaries_and_threshold(self):
        titles = ["Night Moves", "Last Night", "Nights", "Midnight Rain", "Silent night", "Night Fever", "Knight Rider", "Day"]
        out = ff._title_words(ctx(self.tracks(titles), words=["night"]))
        self.assertEqual(len(out), 1)
        self.assertIn("제목에 ‘night’ 단어가 들어간 곡을 5개", out[0]["text"])           # Night Moves, Last Night, Nights, Silent night, Night Fever (Midnight·Knight 는 제외)
        self.assertEqual(ff._title_words(ctx(self.tracks(titles[:4]), words=["night"])), [])  # 5개 미만

    def test_title_word_korean_substring(self):
        out = ff._title_words(ctx(self.tracks([f"{i}번째 밤" for i in range(5)] + ["낮"]), words=["밤"]))
        self.assertIn("‘밤’ 단어가 들어간 곡을 5개", out[0]["text"])

    def test_top_word_ignores_stop_words(self):
        titles = [f"The Song {i}" for i in range(ff.MIN_TOP_WORD_TRACKS)] + ["Remaster Remastered"] * 20
        out = ff._top_title_word(ctx(self.tracks(titles)))
        self.assertIn("‘song’ (8곡)이에요", out[0]["text"])
        self.assertEqual(ff._top_title_word(ctx(self.tracks(titles[:5]))), [])

    def test_title_length(self):
        long_title = "L" * 70
        out = ff._title_length(ctx(self.tracks([long_title, "4", "Normal"])))
        by = {f["id"]: f["text"] for f in out}
        self.assertIn("70글자", by["long_title:long"])
        self.assertIn("…", by["long_title:long"])                         # 너무 긴 제목은 잘라서 보여 줌
        self.assertIn("‘4’ (A), 1글자", by["long_title:short"])
        self.assertEqual(ff._title_length(ctx(self.tracks(["Medium title", "Another one"]))), [])

    def test_same_title_across_artists_skips_generic(self):
        rows = [("2025-01-01 10:00:00", a, "Al", "Eureka") for a in ("A", "B", "C")] + [("2025-01-01 11:00:00", a, "Al", "Intro") for a in "ABCD"]
        out = ff._same_title(ctx(rows))
        self.assertIn("‘Eureka’ 라는 제목의 곡을 3명", out[0]["text"])
        self.assertEqual(ff._same_title(ctx(rows[:2])), [])

    def test_self_titled_and_reissue(self):
        rows = [("2025-01-01 10:00:00", n, n, "T") for n in ("Weezer", "Slint", "Yes")] + [("2025-01-01 11:00:00", "X", "Other", "T")]
        self.assertIn("셀프 타이틀’ 앨범을 3개", ff._self_titled(ctx(rows))[0]["text"])
        self.assertEqual(ff._self_titled(ctx(rows[:2])), [])
        reissues = [("2025-01-01 10:00:00", f"A{i}", f"Album {i} (2011 Remaster)", "T") for i in range(ff.MIN_REISSUE_ALBUMS)]
        self.assertIn("리마스터·에디션 표기가 붙은 앨범을 10개", ff._reissues(ctx(reissues))[0]["text"])
        self.assertEqual(ff._reissues(ctx(reissues[:-1])), [])


class ImmersionFactsTest(unittest.TestCase):
    def test_repeat_in_day(self):
        rows = day_rows("2025-01-01", ff.MIN_REPEAT_IN_DAY, track="Snow") + day_rows("2025-01-02", 3, track="Snow")
        out = ff._repeat_in_day(ctx(rows))
        self.assertIn("같은 곡을 8번 반복한 날이 있어요: 2025년 1월 1일, A의 ‘Snow’", out[0]["text"])
        self.assertEqual(ff._repeat_in_day(ctx(rows[: ff.MIN_REPEAT_IN_DAY - 1])), [])

    def test_artist_run_breaks_on_gap_and_other_artist(self):
        rows = day_rows("2025-01-01", 10, artist="A", track="a{i}") + day_rows("2025-01-01", 20, artist="B", track="b{i}", start_hour=12)
        out = ff._artist_run(ctx(rows))
        self.assertIn("B만 연달아 20곡", out[0]["text"])
        gap = day_rows("2025-01-01", 8, artist="B", track="b{i}", start_hour=10) + day_rows("2025-01-01", 8, artist="B", track="c{i}", start_hour=15)   # 1시간 넘게 쉬면 끊김
        self.assertEqual(ff._artist_run(ctx(gap)), [])

    def test_album_binge(self):
        rows = []
        for d in range(ff.MIN_ALBUM_BINGES):
            rows += day_rows(f"2025-01-{d + 1:02d}", ff.MIN_ALBUM_RUN, artist="A", album="Dream", track=f"t{d}-{{i}}")
        out = ff._album_binge(ctx(rows))
        self.assertIn("정주행(6곡 이상)이 3번 있었어요", out[0]["text"])
        self.assertIn("‘Dream’ — A (3번)", out[0]["text"])
        self.assertEqual(ff._album_binge(ctx(rows[: -ff.MIN_ALBUM_RUN])), [])

    def test_streak(self):
        rows = [(f"{(date(2025, 1, 1) + timedelta(days=i)).isoformat()} 10:00:00", "A", "Al", f"T{i}") for i in range(ff.MIN_STREAK_DAYS)]
        rows.append(("2025-03-01 10:00:00", "A", "Al", "later"))
        out = ff._streak(ctx(rows))
        self.assertIn("최장 14일 연속", out[0]["text"])
        self.assertIn("2025년 1월 1일 ~ 2025년 1월 14일", out[0]["text"])
        self.assertEqual(ff._streak(ctx(rows[: ff.MIN_STREAK_DAYS - 1])), [])

    def test_one_play_share(self):
        titles = [f"T{i}" for i in range(ff.MIN_DISTINCT_FOR_ONE_PLAY)]
        rows = [(f"2025-01-{1 + i // 20:02d} 10:{(i % 20) * 3:02d}:00", "A", "Al", t) for i, t in enumerate(titles)]
        rows += [("2025-02-01 10:00:00", "A", "Al", "T0")] * 10                         # 10곡은 두 번
        # 같은 곡 10개 행이 아니라 곡 0 하나가 11번이 되므로 한 번만 들은 곡은 49개
        out = ff._one_play(ctx(rows))
        self.assertIn("들은 곡 50개 중 98%(49곡)는 딱 한 번만", out[0]["text"])
        self.assertEqual(ff._one_play(ctx(rows[:20])), [])

    def test_comeback(self):
        rows = [("2024-01-10 10:00:00", "A", "Al", "Old"), ("2025-03-01 10:00:00", "A", "Al", "Mid"), ("2025-03-02 10:00:00", "A", "Al", "Old"), ("2025-03-03 10:00:00", "B", "Al", "X"), ("2025-03-04 10:00:00", "B", "Al", "X")]
        out = ff._comeback(ctx(rows))
        self.assertIn("1년 1개월 만에 다시 들은 곡이 있어요: A의 ‘Old’ (2024년 1월 10일 → 2025년 3월 2일)", out[0]["text"])
        self.assertEqual(ff._comeback(ctx(rows[1:])), [])                                 # 1년을 안 넘기면 없음


class TimeFactsTest(unittest.TestCase):
    def test_night_owl(self):
        rows = day_rows("2025-01-01", ff.MIN_NIGHT_PLAYS, artist="Owl", track="n{i}", start_hour=3, step_min=2) + day_rows("2025-01-02", 5, artist="Day", track="d{i}")
        out = ff._night_owl(ctx(rows))
        self.assertIn("새벽 3~5시에 들은 곡이 30개예요", out[0]["text"])
        self.assertIn("단골은 Owl (30회)예요", out[0]["text"])
        self.assertEqual(ff._night_owl(ctx(rows[: ff.MIN_NIGHT_PLAYS - 1])), [])

    def test_favorite_slot(self):
        # 2025-01-06 은 월요일: 20시에 몰아 듣기
        rows = day_rows("2025-01-06", ff.MIN_PLAYS_FOR_SLOT, track="t{i}", start_hour=20, step_min=0)
        out = ff._favorite_slot(ctx(rows))
        self.assertIn("월요일 20시 무렵", out[0]["text"])
        self.assertEqual(ff._favorite_slot(ctx(rows[:50])), [])

    def test_first_of_day(self):
        rows = []
        for d in range(ff.MIN_FIRST_OF_DAY):
            rows += [(f"2025-02-{d + 1:02d} 08:00:00", "Morning", "Al", f"m{d}"), (f"2025-02-{d + 1:02d} 09:00:00", "Other", "Al", f"o{d}")]
        out = ff._first_of_day(ctx(rows))
        self.assertIn("Morning (10일)이에요", out[0]["text"])
        self.assertEqual(ff._first_of_day(ctx(rows[: 2 * (ff.MIN_FIRST_OF_DAY - 1)])), [])

    def test_past_midnight(self):
        rows = [(f"2025-02-{d + 1:02d} 01:00:00", "A", "Al", f"t{d}") for d in range(ff.MIN_PAST_MIDNIGHT_DAYS)] + [("2025-03-01 12:00:00", "A", "Al", "x")]
        out = ff._past_midnight(ctx(rows))
        self.assertIn("들은 날이 10일이에요 (음악을 들은 11일 중 91%)", out[0]["text"])
        self.assertEqual(ff._past_midnight(ctx(rows[:-3])), [])

    def test_weekend_more_and_less(self):
        # 2025-01-04(토)~: 4주 동안 주말에만 하루 10곡
        rows = []
        for w in range(4):
            for off in (0, 1):                                                           # 토, 일
                rows += day_rows((date(2025, 1, 4) + timedelta(days=7 * w + off)).isoformat(), 10, track=f"w{w}{off}-{{i}}")
        rows += day_rows("2025-01-06", 1, track="mon") + day_rows("2025-01-31", 1, track="fri")
        out = ff._weekend(ctx(rows))
        self.assertIn("하루 평균", out[0]["text"])
        self.assertIn("더 들어요", out[0]["text"])
        weekday_heavy = [r for w in range(4) for r in day_rows((date(2025, 1, 6) + timedelta(days=7 * w)).isoformat(), 10, track=f"m{w}-{{i}}")] + day_rows("2025-01-04", 1, track="sat") + day_rows("2025-02-02", 1, track="sun")
        self.assertIn("적게 들어요", ff._weekend(ctx(weekday_heavy))[0]["text"])
        self.assertEqual(ff._weekend(ctx(rows[:10])), [])                                # 28일 미만

    def test_biggest_day(self):
        rows = day_rows("2025-01-01", ff.MIN_BIGGEST_DAY, artist="Star", track="s{i}", step_min=1) + day_rows("2025-01-02", 5)
        out = ff._biggest_day(ctx(rows))
        self.assertIn("2025년 1월 1일, 무려 50곡이에요. 그날의 주인공은 Star (50곡)이에요", out[0]["text"])
        self.assertEqual(ff._biggest_day(ctx(day_rows("2025-01-01", 10))), [])


class DiscoveryFactsTest(unittest.TestCase):
    def rows_for_new(self, n_new):
        rows = day_rows("2026-08-01", 5, artist="Old", track="o{i}")
        for k in range(n_new):
            rows += day_rows(f"2026-10-{k + 1:02d}", 2 + k, artist=f"New{k}", track=f"n{k}-{{i}}")
        return rows

    def test_new_artists_this_month(self):
        out = ff._new_artists(ctx(self.rows_for_new(ff.MIN_NEW_ARTISTS)))
        self.assertIn("이번 달에 처음 들은 아티스트가 3명이에요", out[0]["text"])
        self.assertIn("New2 (4회)예요", out[0]["text"])
        self.assertEqual(ff._new_artists(ctx(self.rows_for_new(ff.MIN_NEW_ARTISTS - 1))), [])

    def test_new_artists_not_for_the_first_month(self):
        rows = [(f"2026-10-{k + 1:02d} 10:00:00", f"N{k}", "Al", "T") for k in range(5)]
        self.assertEqual(ff._new_artists(ctx(rows)), [])

    def test_fast_fall(self):
        rows = day_rows("2025-01-01", 5, artist="Old", track="o{i}")                          # 기록 초반부터 있던 아티스트는 제외
        rows += day_rows("2025-03-01", ff.MIN_FAST_FALL, artist="Crush", track="c{i}", step_min=2)
        rows += day_rows("2025-04-01", 3, artist="Later", track="l{i}")
        out = ff._fast_fall(ctx(rows))
        self.assertIn("일주일 만에 15번이나 들은 아티스트는 Crush (첫 재생 2025년 3월 1일)이에요", out[0]["text"])
        self.assertEqual(ff._fast_fall(ctx(rows[:5] + rows[-3:])), [])


class WordsFileTest(unittest.TestCase):
    def write(self, text):
        p = Path(tempfile.mkdtemp()) / "fun_words.txt"
        p.write_text(text, encoding="utf-8")
        return p

    def test_parse_comments_and_blank(self):
        self.assertEqual(ff.load_words(self.write("# 설명\n\nnight\n 밤 \n")), ["night", "밤"])

    def test_missing_or_empty_falls_back_to_defaults(self):
        self.assertEqual(ff.load_words(Path(tempfile.mkdtemp()) / "none.txt"), ff.DEFAULT_WORDS)
        self.assertEqual(ff.load_words(self.write("# 비었음\n")), ff.DEFAULT_WORDS)

    def test_repo_file_has_words(self):
        self.assertTrue(ff.load_words())


class KoDateTest(unittest.TestCase):
    def test_format(self):
        self.assertEqual(ff.ko_date("2024-06-02"), "2024년 6월 2일")
        self.assertEqual(ff.ko_date("2024-12-31 10:00:00"), "2024년 12월 31일")


if __name__ == "__main__":
    unittest.main()
