// 초 -> "12시간 5분" (1시간 미만이면 "35분")
export function fmtHM(seconds: number): string {
  const minutes = Math.round(seconds / 60);
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h.toLocaleString()}시간 ${m}분` : `${m}분`;
}

export type Metric = "plays" | "time";

// 그래프·히트맵 값 표시: 횟수는 "N회", 시간(분 단위 값)은 "12시간 5분"
export const makeFmt = (metric: Metric) => (v: number) => (metric === "time" ? fmtHM(v * 60) : `${v}회`);

const WEEKDAYS_KO = ["일", "월", "화", "수", "목", "금", "토"];

// "2026-10-03" -> "2026-10-03 (토)". 날짜 형식이 아니면 그대로 돌려준다.
export function withWeekday(date: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(date);
  if (!m) return date;
  const day = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]))).getUTCDay();   // UTC 로 계산해 시간대 영향이 없다
  return `${date} (${WEEKDAYS_KO[day]})`;
}
