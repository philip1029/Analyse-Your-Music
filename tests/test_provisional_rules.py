"""preprocess.judge 의 provisional 규칙(둘째 행이 다른 곡과 겹치는 2회 묶음) 테스트 (합성 데이터). 실행:
    python3 -m unittest discover -s tests -v
"""

import sys
import unittest
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import preprocess as pp  # noqa: E402

BASE = 1_800_000_000
LEN = 200
KST = timezone(timedelta(hours=9))


class _Durations:
    def candidates(self, artist, track):
        return ({LEN}, "local") if track == "Song" else (set(), None)


def row(uts, track, source="L"):
    return {"uts": str(uts), "artist": "A", "album": "Al", "track": track, "source": source}


def judge(rows, log=None):
    state = {"frozen_through_uts": 0, "provisional_through_uts": 0}
    return pp.judge(rows, state, log, lambda need: _Durations(), None)


class ProvisionalPairTest(unittest.TestCase):
    def pair(self, *extra):
        return [row(BASE, "Song"), row(BASE + LEN, "Song"), *extra]

    def test_second_only_clash_removes_the_second_row_with_its_own_rule(self):
        rows = self.pair(row(BASE + LEN + 1, "Other"))
        removals, pending, _ = judge(rows)
        self.assertEqual({i: v["rule"] for i, v in removals.items()}, {1: "provisional:pair_second_clash"})
        self.assertEqual(removals[1]["confidence"], "provisional")
        self.assertIn(f"first_uts={BASE}", removals[1]["detail"])

    def test_both_clash_keeps_the_existing_rule_name(self):
        rows = self.pair(row(BASE - 1, "Other"), row(BASE + LEN + 2, "Third"))
        removals, _, _ = judge(rows)
        self.assertEqual({v["rule"] for v in removals.values()}, {"provisional:pair_both_clash"})
        self.assertEqual(len(removals), 1)

    def test_first_only_clash_and_no_clash_are_not_removed(self):
        for extra in ([row(BASE - 1, "Other")], [row(BASE + 900, "Other")]):
            removals, pending, _ = judge(self.pair(*extra))
            self.assertEqual(removals, {})
            self.assertEqual(pending["pair_other"], 1)

    def test_apple_rows_are_not_part_of_the_pair(self):
        rows = [row(BASE, "Song", "A"), row(BASE + LEN, "Song", "L"), row(BASE + LEN + 1, "Other")]
        self.assertEqual(judge(rows)[0], {})

    def test_three_plays_are_left_alone(self):
        rows = [row(BASE, "Song"), row(BASE + LEN, "Song"), row(BASE + 2 * LEN, "Song"), row(BASE + 2 * LEN + 1, "Other")]
        removals, pending, _ = judge(rows)
        self.assertEqual(removals, {})
        self.assertEqual(pending["run_3plus"], 1)

    def test_log_covered_period_is_decided_by_the_log_not_by_clash(self):
        date = datetime.fromtimestamp(BASE, timezone.utc).astimezone(KST).strftime("%Y-%m-%d")
        counts = defaultdict(int, {("Song", date): 2})                       # 애플 로그가 그날 2번 재생을 확인
        log = {"counts": counts, "end_uts": BASE + 10_000, "catalog": None, "durations": {}}
        rows = self.pair(row(BASE + LEN + 1, "Other"))
        removals, _, _ = judge(rows, log)
        self.assertEqual(removals, {})                                       # 겹침이 있어도 로그가 확인했으니 유지


if __name__ == "__main__":
    unittest.main()
