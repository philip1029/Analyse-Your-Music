"""
"🔄 최신 스크롭 불러오기"의 진행 상황. 새로고침은 여러 단계(Last.fm 받기 → 전처리 → 표기 통일 → 길이·태그 채우기)를 차례로 돌아서
오래 걸리는데, 화면이 /api/refresh/status 를 짧게 물어 진행률 막대를 그릴 수 있게 현재 단계와 백분율을 들고 있는다.
단계마다 비중(weight)이 달라 막대가 한 단계에서 오래 멈춰 보이지 않게 대략 걸리는 시간에 맞춘다. 첫 단계(받기)는 페이지 수를 알면 그 안에서도 움직인다.
"""

import threading
import time

# (키, 화면에 보일 이름, 비중)
STEPS = [
    ("fetch", "Last.fm에서 새 스크롭 받는 중", 40),
    ("preprocess", "가짜·중복 기록 정리 중", 15),
    ("artists", "아티스트 표기 통일 중", 5),
    ("titles", "곡·앨범 제목 통일 중", 5),
    ("durations", "새 곡 길이 채우는 중", 20),
    ("tags", "아티스트 태그 채우는 중", 12),
    ("years", "앨범 발매연도 조회 시작", 3),
]
_TOTAL = sum(w for _, _, w in STEPS)


class RefreshProgress:
    def __init__(self):
        self._lock = threading.Lock()
        self._reset()

    def _reset(self):
        self._running = False
        self._index = -1
        self._sub = 0.0               # 현재 단계 안의 진행 (0~1)
        self._detail = ""
        self._started = 0.0
        self._done = False

    def start(self) -> bool:
        """시작한다. 이미 돌고 있으면 False (동시에 두 번 돌리지 않는다)."""
        with self._lock:
            if self._running:
                return False
            self._reset()
            self._running = True
            self._started = time.time()
            return True

    def begin(self, key: str) -> None:
        """다음 단계로 넘어간다. 앞 단계는 끝난 것으로 본다."""
        with self._lock:
            for i, (k, _, _) in enumerate(STEPS):
                if k == key:
                    self._index, self._sub, self._detail = i, 0.0, ""
                    return

    def sub(self, done: int, total: int, detail: str = "") -> None:
        """현재 단계 안에서 total 중 done 만큼 했다 (예: 페이지 3/10)."""
        with self._lock:
            self._sub = min(1.0, done / total) if total > 0 else 0.0
            self._detail = detail

    def finish(self) -> None:
        with self._lock:
            self._running = False
            self._done = True
            self._sub = 0.0

    def snapshot(self) -> dict:
        with self._lock:
            if self._index < 0:
                percent = 0.0
            else:
                before = sum(w for _, _, w in STEPS[: self._index])
                percent = (before + STEPS[self._index][2] * self._sub) / _TOTAL * 100
            if self._done:
                percent = 100.0
            label = STEPS[self._index][1] if self._index >= 0 else "준비 중"
            return {
                "running": self._running,
                "done": self._done,
                "percent": round(percent, 1),
                "label": "완료" if self._done else label,
                "detail": self._detail,
                "step": max(self._index, 0) + 1,
                "steps": len(STEPS),
                "elapsed": round(time.time() - self._started, 1) if self._started else 0.0,
            }
