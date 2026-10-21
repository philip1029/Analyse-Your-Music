// 월별 재생 분포(날짜 편향도)를 보여 주는 공용 조각: 타입, 미니 막대 그래프, 한 줄 설명

// 월별 재생 분포로 본 "꾸준함". evenness 1 = 모든 달에 고르게, 0 = 한 달에 몰림
export type Consistency = {
  plays: number;
  first_month: string;
  last_month: string;
  months: number;
  active_months: number;
  months_since_last: number;
  evenness: number | null;
  bias: number | null;
  peak_month: string;
  peak_share: number;
  monthly: number[];
};

export type TopItem = {
  name: string;
  count: number;
  artist: string | null;
  album?: string | null;
  duration?: number | null;
  seconds?: number;                 // 청취 시간 순일 때: 횟수 x 곡 길이(초)
  consistency?: Consistency | null;
};

export type ConsistencyItem = Consistency & { key: string; name: string; artist: string | null; album?: string | null; duration?: number | null };

export type ConsistencyResult = {
  category: "artist" | "track" | "album";
  months: string[];
  criteria: { min_plays: number; min_months: number };
  total_candidates: number;
  results: ConsistencyItem[];
};

// 월별 재생 수 막대 미니 그래프 (전체 기간 달 기준이라 "지금은 안 듣는" 항목은 오른쪽이 비어 보인다)
export function Sparkline({ monthly, months, width = 96, height = 20 }: { monthly: number[]; months: string[]; width?: number; height?: number }) {
  const max = Math.max(...monthly, 1);
  const bw = width / monthly.length;
  return (
    <svg width={width} height={height} style={{ flexShrink: 0 }} role="img" aria-label="월별 재생 수">
      {monthly.map((c, i) => {
        const h = c === 0 ? 1 : Math.max(2, (c / max) * height);
        return (
          <rect key={i} x={i * bw} y={height - h} width={Math.max(bw - 0.6, 0.5)} height={h} fill={c === 0 ? "#555" : "#8884d8"}>
            <title>{`${months[i]}: ${c}회`}</title>
          </rect>
        );
      })}
    </svg>
  );
}

export function consistencyText(c: Consistency, plays?: number): string {
  const head = plays === undefined ? "" : `${plays.toLocaleString()}회 · `;
  if (c.evenness === null) return `${head}${c.first_month} 시작 · 아직 한 달`;
  const gone = c.months_since_last >= 1 ? ` · 마지막 청취 ${c.months_since_last}개월 전` : " · 이번 달에도 들음";
  return `${head}고름 ${Math.round(c.evenness * 100)}% · ${c.active_months}/${c.months}개월 청취${gone}`;
}

export function ConsistencyLine({ c, months, plays }: { c: Consistency | null | undefined; months: string[]; plays?: number }) {
  if (!c || c.evenness === null) return null;        // 한 달뿐인 기간(월 선택 등)에서는 "꾸준함"이 의미 없어 숨긴다
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 2, marginTop: 3, textAlign: "left" }}>
      <Sparkline monthly={c.monthly} months={months} width={Math.min(120, months.length * 4)} height={16} />
      <span style={{ color: "#888", fontSize: "0.75rem" }}>{consistencyText(c, plays)}</span>
    </div>
  );
}
