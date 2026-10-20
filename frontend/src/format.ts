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
