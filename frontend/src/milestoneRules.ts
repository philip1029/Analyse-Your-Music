// 다음 이정표 계산 (규칙 기반, AI 없음). 화면과 분리해 둔 순수 함수들.

// "딱 떨어지는" 목표: 1, 1.5, 2, 3, 5, 7.5 × 10^n  (예: 1,000 · 1,500 · 2,000 · 3,000 · 5,000 · 7,500 · 10,000 …)
const STEPS = [1, 1.5, 2, 3, 5, 7.5, 10];

function ladder(value: number): { prev: number; next: number } {
  if (!(value >= 0)) return { prev: 0, next: 100 };
  let p = 1;
  while (p * 10 <= value) p *= 10;               // value 이하의 가장 큰 10의 거듭제곱
  let prev = 0;
  for (const m of STEPS) {
    const t = m * p;
    if (t > value) return { prev, next: t };
    prev = t;
  }
  return { prev, next: 10 * p };                    // 여기 오지 않지만 안전하게
}

export type Milestone = {
  current: number;
  prev: number;          // 직전 이정표 (진행 막대의 시작)
  target: number;        // 다음 이정표
  remaining: number;
  progress: number;      // 0~1, prev → target 구간 안에서의 위치
  perDay: number | null; // 최근 속도 (하루당)
  days: number | null;   // 도달까지 남은 일수 (속도를 모르거나 너무 오래 걸리면 null)
};

const MAX_DAYS = 365 * 5;

export function nextMilestone(current: number, perDay: number | null): Milestone {
  const { prev, next } = ladder(current);
  const remaining = Math.max(0, next - current);
  const rate = perDay !== null && perDay > 0 ? perDay : null;
  const days = rate !== null ? Math.ceil(remaining / rate) : null;
  return {
    current,
    prev,
    target: next,
    remaining,
    progress: next > prev ? Math.min(1, Math.max(0, (current - prev) / (next - prev))) : 0,
    perDay: rate,
    days: days !== null && days <= MAX_DAYS ? days : null,
  };
}

// 오늘 + days 일
export function etaDate(today: Date, days: number): Date {
  const d = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  d.setDate(d.getDate() + days);
  return d;
}

// 남은 일수를 사람이 읽는 말로: "내일" · "약 12일 뒤" · "약 3개월 뒤" · "약 1년 2개월 뒤"
export function untilText(days: number): string {
  if (days <= 0) return "오늘 안에";
  if (days === 1) return "내일";
  if (days < 60) return `약 ${days}일 뒤`;
  const months = Math.round(days / 30.4);
  if (months < 12) return `약 ${months}개월 뒤`;
  const y = Math.floor(months / 12);
  const m = months % 12;
  return m === 0 ? `약 ${y}년 뒤` : `약 ${y}년 ${m}개월 뒤`;
}

export const ymd = (d: Date) => `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일`;
export const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
