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

// "2026-03-05" -> "7개월 전" / "1년 2개월 전" / "12일 전" / "오늘". today 는 테스트용 (기본: 지금, 한국 시간 날짜 기준).
export function agoText(date: string, today?: string): string {
  const parse = (d: string) => {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(d);
    return m ? { y: Number(m[1]), mo: Number(m[2]), d: Number(m[3]) } : null;
  };
  const now = today ?? new Date(Date.now() + 9 * 3600 * 1000).toISOString().slice(0, 10);   // KST 날짜
  const a = parse(date);
  const b = parse(now);
  if (!a || !b) return "";
  let months = (b.y - a.y) * 12 + (b.mo - a.mo) - (b.d < a.d ? 1 : 0);
  if (months < 0) months = 0;
  if (months === 0) {
    const days = Math.round((Date.UTC(b.y, b.mo - 1, b.d) - Date.UTC(a.y, a.mo - 1, a.d)) / 86400000);
    return days <= 0 ? "오늘" : `${days}일 전`;
  }
  const y = Math.floor(months / 12);
  const m = months % 12;
  return y ? `${y}년${m ? ` ${m}개월` : ""} 전` : `${m}개월 전`;
}
