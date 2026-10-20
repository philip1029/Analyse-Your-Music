import { useEffect, useState, useCallback, useRef } from "react";
import { BASE_URL } from "./config";
import { Cover } from "./Cover";
import { Library } from "./Library";
import { RankRow, type RankKind } from "./RankRow";
import { fmtHM, makeFmt, withWeekday, type Metric } from "./format";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
  RadarChart,
  Radar,
  PolarGrid,
  PolarAngleAxis,
  PolarRadiusAxis,
  Legend,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

type DailyPoint = { date: string; count: number };

type TimeSummary = {
  total_seconds: number;
  coverage: number;
  days: number;
  active_days: number;
  avg_seconds_per_day: number;
  avg_seconds_per_active_day: number;
  busiest_day: { date: string; seconds: number; plays: number } | null;
};

type DayTrack = { time: string; artist: string; track: string; album: string };

type DayDetail = {
  date: string;
  total_plays: number;
  unique_artists: number;
  unique_tracks: number;
  top_artists: { name: string; count: number }[];
  tracks: DayTrack[];
};

type DiscoverySummary = {
  track: { total_new: number; months: string[]; counts: number[] };
  artist: { total_new: number; months: string[]; counts: number[] };
  album: { total_new: number; months: string[]; counts: number[] };
};

type DiscoveryItem = {
  name: string;
  artist: string | null;
  album?: string | null;
  first_listened: string;
};

type Stats = {
  total_scrobbles: number;
  unique_tracks: number;
  unique_artists: number;
  unique_albums: number;
  first_scrobble: string | null;
  last_scrobble: string | null;
};

type ChartPoint = { label: string; count: number };

type ValidationResult = {
  valid: boolean;
  errors: string[];
  warnings: string[];
  total_rows: number;
};

type ArtistTagResult = {
  artist: string;
  play_count: number;
  tags: string[];
};

type ArtistTagsPage = {
  page: number;
  page_size: number;
  total_artists: number;
  total_pages: number;
  artists: ArtistTagResult[];
};

type TagDistribution = {
  tags: { tag: string; score: number }[];
  covered_artists: number;
  total_artists: number;
};

// 월별 재생 분포로 본 "꾸준함". evenness 1 = 모든 달에 고르게, 0 = 한 달에 몰림
type Consistency = {
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

type TopItem = {
  name: string;
  count: number;
  artist: string | null;
  album?: string | null;
  duration?: number | null;
  seconds?: number;                 // 청취 시간 순일 때: 횟수 x 곡 길이(초)
  consistency?: Consistency | null;
};

type ConsistencyItem = Consistency & { key: string; name: string; artist: string | null; album?: string | null; duration?: number | null };

type ConsistencyResult = {
  category: "artist" | "track" | "album";
  months: string[];
  criteria: { min_plays: number; min_months: number };
  total_candidates: number;
  results: ConsistencyItem[];
};

type DateRange = {
  start?: string;
  end?: string;
  label: string;
};

type TagEvolution = {
  periods: string[];
  series: { tag: string; values: number[] }[];
};

type DiversityMetric = {
  unique_count: number;
  entropy: number;
  normalized_entropy: number;
  top10pct_concentration: number;
  most_played: { name: string | null; count: number };
};

type Diversity = {
  artist: DiversityMetric;
  track: DiversityMetric;
  album: DiversityMetric;
};

type TabId = "overview" | "listening" | "music" | "library" | "consistency" | "discovery" | "taste" | "data";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "listening", label: "Listening" },
  { id: "music", label: "Music" },
  { id: "library", label: "Library" },
  { id: "consistency", label: "Consistency" },
  { id: "discovery", label: "Discovery" },
  { id: "taste", label: "Taste" },
  { id: "data", label: "Data" },
];

const ALL_TIME: DateRange = { label: "전체 기간" };

function daysAgo(n: number): DateRange {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - n);
  return {
    start: start.toISOString().slice(0, 10),
    end: end.toISOString().slice(0, 10),
    label: `최근 ${n}일`,
  };
}

function yearRange(year: number): DateRange {
  return {
    start: `${year}-01-01`,
    end: `${year}-12-31`,
    label: `${year}년`,
  };
}


// 월별 재생 수 막대 미니 그래프 (전체 기간 달 기준이라 "지금은 안 듣는" 항목은 오른쪽이 비어 보인다)
function Sparkline({ monthly, months, width = 96, height = 20 }: { monthly: number[]; months: string[]; width?: number; height?: number }) {
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

function consistencyText(c: Consistency, plays?: number): string {
  const head = plays === undefined ? "" : `${plays.toLocaleString()}회 · `;
  if (c.evenness === null) return `${head}${c.first_month} 시작 · 아직 한 달`;
  const gone = c.months_since_last >= 1 ? ` · 마지막 청취 ${c.months_since_last}개월 전` : " · 이번 달에도 들음";
  return `${head}고름 ${Math.round(c.evenness * 100)}% · ${c.active_months}/${c.months}개월 청취${gone}`;
}

function ConsistencyLine({ c, months, plays }: { c: Consistency | null | undefined; months: string[]; plays?: number }) {
  if (!c) return null;
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 2, marginTop: 3, textAlign: "left" }}>
      <Sparkline monthly={c.monthly} months={months} width={Math.min(120, months.length * 4)} height={16} />
      <span style={{ color: "#888", fontSize: "0.75rem" }}>{consistencyText(c, plays)}</span>
    </div>
  );
}

// 횟수 / 시간 전환 버튼 (시간 = 스크로블 횟수 x 곡 길이, 끝까지 들었다고 가정한 추정치)
function MetricToggle({ metric, onChange }: { metric: Metric; onChange: (m: Metric) => void }) {
  return (
    <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap", margin: "0.4rem 0 0.8rem" }}>
      {([
        ["plays", "재생 횟수"],
        ["time", "청취 시간"],
      ] as const).map(([m, label]) => (
        <button
          key={m}
          onClick={() => onChange(m)}
          style={{ padding: "0.3rem 0.8rem", fontWeight: metric === m ? "bold" : "normal", border: metric === m ? "2px solid #8884d8" : "1px solid #666" }}
        >
          {label}
        </button>
      ))}
      {metric === "time" && <span style={{ color: "#888", fontSize: "0.8rem" }}>스크로블 횟수 × 곡 길이 (끝까지 들었다고 가정한 추정치)</span>}
    </div>
  );
}

function YearHeatmap({
  year,
  data,
  onDayClick,
  format,
}: {
  year: string;
  data: DailyPoint[];
  onDayClick: (date: string) => void;
  format: (n: number) => string;
}) {
  const countMap = new Map(data.map((d) => [d.date, d.count]));
  const maxCount = Math.max(...data.map((d) => d.count), 1);

  const getColor = (count: number) => {
    if (count === 0) return "#ebedf0";
    const ratio = count / maxCount;
    if (ratio < 0.25) return "#9be9a8";
    if (ratio < 0.5) return "#40c463";
    if (ratio < 0.75) return "#30a14e";
    return "#216e39";
  };

  const startDate = new Date(`${year}-01-01`);
  startDate.setDate(startDate.getDate() - startDate.getDay());
  const endDate = new Date(`${year}-12-31`);

  const weeks: { date: string; count: number }[][] = [];
  const cursor = new Date(startDate);

  while (cursor <= endDate) {
    const week: { date: string; count: number }[] = [];
    for (let i = 0; i < 7; i++) {
      const dateStr = cursor.toISOString().slice(0, 10);
      week.push({ date: dateStr, count: countMap.get(dateStr) ?? 0 });
      cursor.setDate(cursor.getDate() + 1);
    }
    weeks.push(week);
  }

  const cellSize = 12;
  const cellGap = 3;
  const monthLabels: { label: string; x: number }[] = [];
  let lastMonth = -1;

  weeks.forEach((week, wi) => {
    const d = new Date(week[0].date);
    if (d.getFullYear() === Number(year) && d.getMonth() !== lastMonth) {
      monthLabels.push({
        label: d.toLocaleDateString("ko-KR", { month: "short" }),
        x: wi * (cellSize + cellGap),
      });
      lastMonth = d.getMonth();
    }
  });

  const width = weeks.length * (cellSize + cellGap);
  const height = 7 * (cellSize + cellGap) + 20;

  return (
    <div style={{ marginBottom: "1.5rem" }}>
      <h4 style={{ margin: "0 0 0.3rem 0" }}>{year}</h4>
      <div style={{ overflowX: "auto" }}>
        <svg width={width} height={height}>
          {monthLabels.map((m, i) => (
            <text key={i} x={m.x} y={10} fontSize={10} fill="#888">
              {m.label}
            </text>
          ))}
          {weeks.map((week, wi) =>
            week.map((day, di) => {
              const inYear = day.date.startsWith(year);
              return (
                <rect
                  key={`${wi}-${di}`}
                  x={wi * (cellSize + cellGap)}
                  y={di * (cellSize + cellGap) + 20}
                  width={cellSize}
                  height={cellSize}
                  rx={2}
                  fill={inYear ? getColor(day.count) : "transparent"}
                  style={{ cursor: inYear ? "pointer" : "default" }}
                  onClick={() => inYear && onDayClick(day.date)}
                >
                  {inYear && (
                    <title>
                      {withWeekday(day.date)}: {format(day.count)}
                    </title>
                  )}
                </rect>
              );
            })
          )}
        </svg>
      </div>
    </div>
  );
}

function interpolateColor(a: string, b: string, t: number) {
  const ah = parseInt(a.slice(1), 16);
  const bh = parseInt(b.slice(1), 16);
  const ar = (ah >> 16) & 0xff, ag = (ah >> 8) & 0xff, ab = ah & 0xff;
  const br = (bh >> 16) & 0xff, bg = (bh >> 8) & 0xff, bb = bh & 0xff;
  const rr = Math.round(ar + (br - ar) * t);
  const rg = Math.round(ag + (bg - ag) * t);
  const rb = Math.round(ab + (bb - ab) * t);
  return `rgb(${rr},${rg},${rb})`;
}

function ListeningClock({ data, format, noun }: { data: ChartPoint[]; format: (n: number) => string; noun: string }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; hour: number; count: number } | null>(null);

  if (data.length === 0) return null;

  const counts = data.map((d) => d.count);
  const maxCount = Math.max(...counts, 1);
  const busiestHour = counts.indexOf(maxCount);

  const formatHourKorean = (h: number) => {
    const period = h < 12 ? "오전" : "오후";
    let displayHour = h % 12;
    if (displayHour === 0) displayHour = 12;
    return `${period} ${displayHour}시`;
  };

  const size = 320;
  const cx = size / 2;
  const cy = size / 2;
  const rInner = 55;
  const rOuterMax = size / 2 - 10;
  const gapDeg = 2;

  const polarToCartesian = (r: number, angleDeg: number) => {
    const angleRad = ((angleDeg - 90) * Math.PI) / 180;
    return { x: cx + r * Math.cos(angleRad), y: cy + r * Math.sin(angleRad) };
  };

  const describeWedge = (rOuter: number, startAngle: number, endAngle: number) => {
    const startOuter = polarToCartesian(rOuter, endAngle);
    const endOuter = polarToCartesian(rOuter, startAngle);
    const startInner = polarToCartesian(rInner, endAngle);
    const endInner = polarToCartesian(rInner, startAngle);
    const largeArcFlag = endAngle - startAngle <= 180 ? "0" : "1";
    return [
      "M", startOuter.x, startOuter.y,
      "A", rOuter, rOuter, 0, largeArcFlag, 0, endOuter.x, endOuter.y,
      "L", endInner.x, endInner.y,
      "A", rInner, rInner, 0, largeArcFlag, 1, startInner.x, startInner.y,
      "Z",
    ].join(" ");
  };

  const handleMove = (e: React.MouseEvent, h: number) => {
    const rect = containerRef.current?.getBoundingClientRect();
    if (!rect) return;
    setTooltip({ x: e.clientX - rect.left, y: e.clientY - rect.top, hour: h, count: data[h].count });
  };

  return (
    <div ref={containerRef} style={{ position: "relative", display: "flex", alignItems: "center", gap: "2.5rem", flexWrap: "wrap" }}>
      <style>{`
        @keyframes clockWedgeGrow {
          from { transform: scale(0); }
          to { transform: scale(1); }
        }
      `}</style>

      <svg width={size} height={size}>
        {data.map((d, h) => {
          const startAngle = h * 15 + gapDeg / 2;
          const endAngle = (h + 1) * 15 - gapDeg / 2;
          const ratio = d.count / maxCount;
          const rOuter = rInner + (rOuterMax - rInner) * ratio;
          const isHovered = tooltip?.hour === h;

        return (
          <g
            key={h}
            onMouseMove={(e) => handleMove(e, h)}
            onMouseLeave={() => setTooltip(null)}
            style={{ cursor: "pointer" }}
          >
            <path d={describeWedge(rOuterMax, startAngle, endAngle)} fill={isHovered ? "#ddd" : "#eee"} />
            {d.count > 0 && (
              <path
                d={describeWedge(rOuter, startAngle, endAngle)}
                fill={interpolateColor("#bfdbfe", "#2563eb", ratio)}
                stroke={isHovered ? "#111" : "none"}
                strokeWidth={isHovered ? 1.5 : 0}
                style={{
                  transformOrigin: `${cx}px ${cy}px`,
                  animation: `clockWedgeGrow 0.4s ease-out ${h * 0.02}s both`,
                }}
              />
            )}
          </g>
        );
        })}
        <text x={cx} y={cy - rInner * 0.55} textAnchor="middle" dominantBaseline="middle" fontSize={13} fill="#888">00</text>
        <text x={cx + rInner * 0.6} y={cy} textAnchor="middle" dominantBaseline="middle" fontSize={13} fill="#888">06</text>
        <text x={cx} y={cy + rInner * 0.65} textAnchor="middle" dominantBaseline="middle" fontSize={13} fill="#888">12</text>
        <text x={cx - rInner * 0.6} y={cy} textAnchor="middle" dominantBaseline="middle" fontSize={13} fill="#888">18</text>
      </svg>

      <div>
        <p style={{ color: "#888", margin: "0 0 4px 0" }}>가장 붐비는 시간대</p>
        <p style={{ fontSize: "1.8rem", fontWeight: "bold", margin: "0 0 1.2rem 0" }}>
          {formatHourKorean(busiestHour)}
        </p>
        <p style={{ color: "#888", margin: "0 0 4px 0" }}>가장 바쁜 시간대의 {noun}</p>
        <p style={{ fontSize: "1.8rem", fontWeight: "bold", margin: 0 }}>{format(maxCount)}</p>
      </div>

      {tooltip && (
        <div
          style={{
            position: "absolute",
            left: tooltip.x + 14,
            top: tooltip.y + 14,
            background: "#222",
            color: "white",
            padding: "0.5rem 0.75rem",
            borderRadius: 6,
            fontSize: "0.85rem",
            pointerEvents: "none",
            whiteSpace: "nowrap",
            boxShadow: "0 2px 8px rgba(0,0,0,0.3)",
            zIndex: 20,
          }}
        >
          <div style={{ fontWeight: "bold" }}>{formatHourKorean(tooltip.hour)}</div>
          <div>{format(tooltip.count)}</div>
        </div>
      )}
    </div>
  );
}

function ContributionHeatmap({
  data,
  onDayClick,
  format,
}: {
  data: DailyPoint[];
  onDayClick: (date: string) => void;
  format: (n: number) => string;
}) {
  if (data.length === 0) return null;

  const years = Array.from(new Set(data.map((d) => d.date.slice(0, 4)))).sort();

  return (
    <div>
      {years.map((year) => (
        <YearHeatmap key={year} year={year} data={data} onDayClick={onDayClick} format={format} />
      ))}
    </div>
  );
}

function SortedTagTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: { dataKey: string; value: number | null; color: string }[];
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;

  const sorted = payload
    .filter((entry) => entry.value !== null && entry.value !== undefined)
    .sort((a, b) => (b.value ?? 0) - (a.value ?? 0));

  if (sorted.length === 0) return null;

  return (
    <div
      style={{
        background: "white",
        border: "1px solid #ccc",
        borderRadius: 6,
        padding: "0.5rem 0.75rem",
        fontSize: "0.85rem",
      }}
    >
      <div style={{ fontWeight: "bold", marginBottom: 4 }}>{label}</div>
      {sorted.map((entry) => (
        <div key={entry.dataKey} style={{ color: entry.color }}>
          {entry.dataKey}: {entry.value}
        </div>
      ))}
    </div>
  );
}

function DayDetailModal({
  detail,
  loading,
  onClose,
}: {
  detail: DayDetail | null;
  loading: boolean;
  onClose: () => void;
}) {
  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.5)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "white",
          borderRadius: 8,
          padding: "1.5rem",
          width: "min(600px, 90vw)",
          maxHeight: "80vh",
          overflowY: "auto",
        }}
      >
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: "1rem",
          }}
        >
          <h3 style={{ margin: 0 }}>{detail ? withWeekday(detail.date) : "불러오는 중..."}</h3>
          <button onClick={onClose} style={{ padding: "0.3rem 0.6rem" }}>
            닫기
          </button>
        </div>

        {loading && <p>불러오는 중...</p>}

        {!loading && detail && detail.total_plays === 0 && <p>이날은 청취 기록이 없어요.</p>}

        {!loading && detail && detail.total_plays > 0 && (
          <>
            <p style={{ color: "#888", marginTop: 0 }}>
              총 {detail.total_plays}회 재생 · 아티스트 {detail.unique_artists}명 · 트랙{" "}
              {detail.unique_tracks}개
            </p>

            <h4 style={{ marginBottom: "0.4rem" }}>많이 들은 아티스트</h4>
            <ul style={{ marginTop: 0 }}>
              {detail.top_artists.map((a) => (
                <li key={a.name}>
                  {a.name} — {a.count}회
                </li>
              ))}
            </ul>

            <h4 style={{ marginBottom: "0.4rem" }}>전체 재생 목록 (시간순)</h4>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
              <thead>
                <tr style={{ textAlign: "left", borderBottom: "1px solid #ddd" }}>
                  <th style={{ padding: "0.3rem" }}>시각</th>
                  <th style={{ padding: "0.3rem" }}>아티스트</th>
                  <th style={{ padding: "0.3rem" }}>트랙</th>
                </tr>
              </thead>
              <tbody>
                {detail.tracks.map((t, i) => (
                  <tr key={i} style={{ borderBottom: "1px solid #f0f0f0" }}>
                    <td style={{ padding: "0.3rem", color: "#888", whiteSpace: "nowrap" }}>{t.time}</td>
                    <td style={{ padding: "0.3rem" }}>{t.artist}</td>
                    <td style={{ padding: "0.3rem" }}>{t.track}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
      </div>
    </div>
  );
}

function App() {
  const [aiPrompt, setAiPrompt] = useState<string | null>(null);
  const [generatingPrompt, setGeneratingPrompt] = useState(false);
  const [copied, setCopied] = useState(false);

  // 전체 기간(선택한 날짜 범위) / 월간 / 주간 프롬프트
  const [promptKind, setPromptKind] = useState<"all" | "month" | "week" | "year">("all");
  const [periodOptions, setPeriodOptions] = useState<
    { key: string; label: string; scrobbles: number; partial: boolean }[]
  >([]);
  const [periodKey, setPeriodKey] = useState("");
  const [promptNote, setPromptNote] = useState<string | null>(null);

  useEffect(() => {
    setAiPrompt(null);
    setPromptNote(null);
    if (promptKind === "all") return;
    fetch(`${BASE_URL}/api/ai-prompt/periods?period=${promptKind}`)
      .then((res) => res.json())
      .then((data) => {
        const options = data.periods ?? [];
        setPeriodOptions(options);
        // 기본값은 가장 최근의 '끝난' 기간 (진행 중인 기간은 목록에서 직접 고를 수 있음)
        setPeriodKey((options.find((o: { partial: boolean }) => !o.partial) ?? options[0])?.key ?? "");
      })
      .catch((err) => setError(err.message));
  }, [promptKind]);

const handleGeneratePrompt = () => {
  setGeneratingPrompt(true);
  setPromptNote(null);
  const url =
    promptKind === "all"
      ? `${BASE_URL}/api/ai-prompt${buildQuery()}`
      : `${BASE_URL}/api/ai-prompt/period?period=${promptKind}&anchor=${encodeURIComponent(periodKey)}`;
  fetch(url)
    .then((res) => res.json())
    .then((data) => {
      if (data.error) {
        setAiPrompt(null);
        setPromptNote(data.error);
        return;
      }
      setAiPrompt(data.prompt);
      if (data.meta) {
        setPromptNote(
          `${data.meta.label} · ${data.meta.scrobbles.toLocaleString()}회` +
            (data.meta.partial ? " · 기록이 일부 기간만 있어요 (일평균 위주로 비교됩니다)" : "")
        );
      }
    })
    .catch((err) => setError(err.message))
    .finally(() => setGeneratingPrompt(false));
};

const handleCopyPrompt = () => {
  if (!aiPrompt) return;
  navigator.clipboard.writeText(aiPrompt);
  setCopied(true);
  setTimeout(() => setCopied(false), 2000);
};

  const [dailyData, setDailyData] = useState<DailyPoint[]>([]);
  // 히트맵·시계·요일·월·연 그래프를 "횟수"로 볼지 "시간(곡 길이 x 횟수)"으로 볼지
  const [metric, setMetric] = useState<Metric>("plays");
  const [timeSummary, setTimeSummary] = useState<TimeSummary | null>(null);
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const [dayDetail, setDayDetail] = useState<DayDetail | null>(null);
  const [loadingDayDetail, setLoadingDayDetail] = useState(false);

  const [discoverySummary, setDiscoverySummary] = useState<DiscoverySummary | null>(null);
  const [discoveryTimeline, setDiscoveryTimeline] = useState<DiscoveryItem[]>([]);

  const [invalidating, setInvalidating] = useState(false);
  const [invalidateMessage, setInvalidateMessage] = useState<string | null>(null);

  const [activeTab, setActiveTab] = useState<TabId>("overview");

  const [dateRange, setDateRange] = useState<DateRange>(ALL_TIME);
  const [filterOpen, setFilterOpen] = useState(false);
  const [tempStart, setTempStart] = useState("");
  const [tempEnd, setTempEnd] = useState("");

  const [stats, setStats] = useState<Stats | null>(null);
  const [hourlyData, setHourlyData] = useState<ChartPoint[]>([]);
  const [weekdayData, setWeekdayData] = useState<ChartPoint[]>([]);
  const [monthlyData, setMonthlyData] = useState<ChartPoint[]>([]);
  const [yearlyData, setYearlyData] = useState<ChartPoint[]>([]);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [topArtists, setTopArtists] = useState<TopItem[]>([]);
  const [topTracks, setTopTracks] = useState<TopItem[]>([]);
  const [topAlbums, setTopAlbums] = useState<TopItem[]>([]);
  const [topMonths, setTopMonths] = useState<string[]>([]);
  // Top 10 기준: 재생 많은 순 / 월별로 고르게(꾸준히) 들은 순
  const [topMode, setTopMode] = useState<"plays" | "even" | "time">("plays");
  const [evenTop, setEvenTop] = useState<{ artist: TopItem[]; track: TopItem[]; album: TopItem[]; months: string[] } | null>(null);
  const [timeTop, setTimeTop] = useState<{ artist: TopItem[]; track: TopItem[]; album: TopItem[]; months: string[] } | null>(null);

  const [consCategory, setConsCategory] = useState<"artist" | "track" | "album">("track");
  const [consSort, setConsSort] = useState<"even" | "biased">("even");
  const [consMinPlays, setConsMinPlays] = useState(20);
  const [consMinMonths, setConsMinMonths] = useState(12);
  const [consData, setConsData] = useState<ConsistencyResult | null>(null);
  const [consLoading, setConsLoading] = useState(false);

  const [tagDistribution, setTagDistribution] = useState<TagDistribution | null>(null);
  const [tagEvolution, setTagEvolution] = useState<TagEvolution | null>(null);
  const [evolutionMode, setEvolutionMode] = useState<"fixed" | "dynamic">("dynamic");

  const [diversity, setDiversity] = useState<Diversity | null>(null);

  const [artistTags, setArtistTags] = useState<ArtistTagResult[]>([]);
  const [tagsPage, setTagsPage] = useState(1);
  const [totalTagsPages, setTotalTagsPages] = useState<number | null>(null);
  const [loadingTags, setLoadingTags] = useState(false);

  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);

  const [cachingTags, setCachingTags] = useState(false);
  const [cacheMessage, setCacheMessage] = useState<string | null>(null);

  const buildQuery = useCallback(
    (extra: Record<string, string | number> = {}) => {
      const params = new URLSearchParams();
      if (dateRange.start) params.set("start", dateRange.start);
      if (dateRange.end) params.set("end", dateRange.end);
      Object.entries(extra).forEach(([k, v]) => params.set(k, String(v)));
      const qs = params.toString();
      return qs ? `?${qs}` : "";
    },
    [dateRange]
  );

  const loadArtistTagsPage = useCallback(
    (page: number) => {
      setLoadingTags(true);
      const qs = buildQuery({ page, page_size: 20 });
      fetch(`${BASE_URL}/api/taste/artists${qs}`)
        .then((res) => res.json())
        .then((data: ArtistTagsPage) => {
          setArtistTags((prev) => (page === 1 ? data.artists : [...prev, ...data.artists]));
          setTagsPage(data.page);
          setTotalTagsPages(data.total_pages);
        })
        .catch((err) => setError(err.message))
        .finally(() => setLoadingTags(false));
    },
    [buildQuery]
  );

  useEffect(() => {
    if (activeTab !== "music" || topMode !== "time") return;
    let cancelled = false;
    const load = (category: "artist" | "track" | "album") =>
      fetch(`${BASE_URL}/api/music/top${buildQuery({ category, limit: 10, metric: "time" })}`)
        .then((res) => res.json())
        .then((d) => ({ months: (d.months ?? []) as string[], items: (d.results ?? []) as TopItem[] }));
    Promise.all([load("artist"), load("track"), load("album")])
      .then(([a, t, al]) => {
        if (!cancelled) setTimeTop({ artist: a.items, track: t.items, album: al.items, months: a.months });
      })
      .catch((err) => setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [activeTab, topMode, buildQuery]);

  useEffect(() => {
    if (activeTab !== "music" || topMode !== "even") return;
    let cancelled = false;
    const load = (category: "artist" | "track" | "album") =>
      fetch(
        `${BASE_URL}/api/music/consistency${buildQuery({ category, sort: "even", min_plays: consMinPlays, min_months: consMinMonths, limit: 10 })}`
      )
        .then((res) => res.json())
        .then((data: ConsistencyResult) => ({
          months: data.months ?? [],
          items: (data.results ?? []).map(
            (r): TopItem => ({ name: r.name, count: r.plays, artist: r.artist, album: r.album ?? null, duration: r.duration ?? null, consistency: r })
          ),
        }));
    Promise.all([load("artist"), load("track"), load("album")])
      .then(([a, t, al]) => {
        if (!cancelled) setEvenTop({ artist: a.items, track: t.items, album: al.items, months: a.months });
      })
      .catch((err) => setError(err.message));
    return () => {
      cancelled = true;
    };
  }, [activeTab, topMode, consMinPlays, consMinMonths, buildQuery]);

  useEffect(() => {
    if (activeTab !== "consistency") return;
    let cancelled = false;
    setConsLoading(true);
    fetch(
      `${BASE_URL}/api/music/consistency${buildQuery({
        category: consCategory,
        sort: consSort,
        min_plays: consMinPlays,
        min_months: consMinMonths,
        limit: 50,
      })}`
    )
      .then((res) => res.json())
      .then((data) => {
        if (!cancelled) setConsData(data.error ? null : data);
      })
      .catch((err) => setError(err.message))
      .finally(() => {
        if (!cancelled) setConsLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [activeTab, consCategory, consSort, consMinPlays, consMinMonths, buildQuery]);

  // 히트맵·청취 시계·요일/월/연 그래프: 횟수 또는 시간 (metric 이 바뀌면 이 그래프들만 다시 받는다)
  useEffect(() => {
    const mq = buildQuery({ metric });
    fetch(`${BASE_URL}/api/listening/daily${mq}`)
      .then((res) => res.json())
      .then((data) => setDailyData(data.days))
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/listening/hourly${mq}`)
      .then((res) => res.json())
      .then((data) => {
        const points = data.hours.map((h: number, i: number) => ({
          label: `${h}시`,
          count: data.counts[i],
        }));
        setHourlyData(points);
      })
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/listening/weekday${mq}`)
      .then((res) => res.json())
      .then((data) => {
        const points = data.weekdays.map((w: string, i: number) => ({
          label: w,
          count: data.counts[i],
        }));
        setWeekdayData(points);
      })
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/listening/monthly${mq}`)
      .then((res) => res.json())
      .then((data) => {
        const points = data.months.map((m: string, i: number) => ({
          label: m,
          count: data.counts[i],
        }));
        setMonthlyData(points);
      })
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/listening/yearly${mq}`)
      .then((res) => res.json())
      .then((data) => {
        const points = data.years.map((y: number, i: number) => ({
          label: String(y),
          count: data.counts[i],
        }));
        setYearlyData(points);
      })
      .catch((err) => setError(err.message));

  }, [buildQuery, metric]);

  const loadAllData = useCallback(() => {
    const qs = buildQuery();

    fetch(`${BASE_URL}/api/stats${qs}`)
      .then((res) => res.json())
      .then(setStats)
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/time/summary${qs}`)
      .then((res) => res.json())
      .then((d) => setTimeSummary(d.error ? null : d))
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/music/top${buildQuery({ category: "artist", limit: 10 })}`)
      .then((res) => res.json())
      .then((data) => setTopArtists(data.results))
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/music/top${buildQuery({ category: "track", limit: 10 })}`)
      .then((res) => res.json())
      .then((data) => setTopTracks(data.results))
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/music/top${buildQuery({ category: "album", limit: 10 })}`)
      .then((res) => res.json())
      .then((data) => {
        setTopAlbums(data.results);
        setTopMonths(data.months ?? []);
      })
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/taste/tag-distribution${qs}`)
      .then((res) => res.json())
      .then(setTagDistribution)
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/taste/evolution${buildQuery({ mode: evolutionMode })}`)
      .then((res) => res.json())
      .then(setTagEvolution)
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/diversity${qs}`)
      .then((res) => res.json())
      .then(setDiversity)
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/validate`)
      .then((res) => res.json())
      .then(setValidation)
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/discovery/summary${qs}`)
      .then((res) => res.json())
      .then(setDiscoverySummary)
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/discovery/timeline${buildQuery({ category: "track", limit: 15 })}`)
      .then((res) => res.json())
      .then((data) => setDiscoveryTimeline(data.results))
      .catch((err) => setError(err.message));

    setArtistTags([]);
    setTagsPage(1);
    setTotalTagsPages(null);
  }, [buildQuery, evolutionMode]);

  useEffect(() => {
    loadAllData();
  }, [loadAllData]);

  useEffect(() => {
    if (artistTags.length === 0 && !loadingTags) {
      loadArtistTagsPage(1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateRange]);

  const handleInvalidateAliasCache = () => {
    setInvalidating(true);
    setInvalidateMessage(null);

    fetch(`${BASE_URL}/api/cache/invalidate-aliases`, { method: "POST" })
      .then((res) => res.json())
      .then((data) => {
        setInvalidateMessage(`캐시 ${data.count}개 삭제됨. 페이지를 새로고침하면 다시 채워집니다.`);
      })
      .catch((err) => setInvalidateMessage(`에러: ${err.message}`))
      .finally(() => setInvalidating(false));
  };

  const handleRefresh = () => {
    setRefreshing(true);
    setRefreshMessage(null);

    fetch(`${BASE_URL}/api/refresh`, { method: "POST" })
      .then((res) => res.json())
      .then((data) => {
        if (data.success) {
          // 새로 받은 기록에 적용된 전처리(가짜/중복 스크로블 정리) 결과를 함께 보여준다.
          const added = /새로 추가된 곡: (\d+)개/.exec(data.output ?? "")?.[1];
          const pre = data.preprocess as
            | { error?: string; removed?: number; pending?: Record<string, number> }
            | null
            | undefined;
          const parts: string[] = [];
          if (added) parts.push(`새 스크로블 ${added}개`);
          if (pre?.error) {
            parts.push(`전처리 실패: ${pre.error}`);
          } else if (pre) {
            if (pre.removed) parts.push(`가짜/중복 의심 ${pre.removed}행 정리`);
            const pendingCount = Object.values(pre.pending ?? {}).reduce((a, b) => a + b, 0);
            if (pendingCount) parts.push(`보류 ${pendingCount}건(지우지 않음)`);
          }
          // 곡/앨범 제목 표기 통일(Apple/Last.fm 대소문자 차이) 결과
          const titles = data.titles as { error?: string; tracks?: number; albums?: number } | null | undefined;
          if (titles?.error) {
            parts.push(`제목 통일 실패: ${titles.error}`);
          } else if (titles && (titles.tracks || titles.albums)) {
            parts.push(`제목 표기 통일 곡 ${titles.tracks ?? 0}행 · 앨범 ${titles.albums ?? 0}행`);
          }
          // 새 곡의 길이 조회 결과
          const durs = data.durations as { error?: string; found?: number; unknown?: number; remaining?: number } | null | undefined;
          if (durs?.error) {
            parts.push(`곡 길이 조회 실패: ${durs.error}`);
          } else if (durs && (durs.found || durs.unknown)) {
            parts.push(`곡 길이 ${durs.found ?? 0}곡 추가${durs.unknown ? ` (못 찾음 ${durs.unknown})` : ""}${durs.remaining ? ` · 남은 ${durs.remaining}곡은 다음에` : ""}`);
          }
          setRefreshMessage(
            `업데이트 완료!${parts.length ? ` (${parts.join(" · ")})` : ""} 잠시 후 새로고침됩니다...`
          );
          // 정리된 행이 있거나 전처리·제목 통일이 실패했을 때는 결과를 읽을 시간을 더 준다.
          const needsTime = Boolean(pre?.error || pre?.removed || titles?.error || titles?.tracks || titles?.albums || durs?.error);
          setTimeout(() => {
            window.location.reload();
          }, needsTime ? 4000 : 1000);
        } else {
          setRefreshMessage(`실패: ${data.error}`);
          setRefreshing(false);
        }
      })
      .catch((err) => {
        setRefreshMessage(`에러: ${err.message}`);
        setRefreshing(false);
      });
  };

  const handleFetchTagCache = () => {
    setCachingTags(true);
    setCacheMessage(null);

    fetch(`${BASE_URL}/api/taste/cache-fetch${buildQuery({ count: 20 })}`, { method: "POST" })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          setCacheMessage(`에러: ${data.error}`);
        } else {
          setCacheMessage(`${data.fetched}명 새로 조회 완료 (${data.covered_artists} / ${data.total_artists})`);
          loadAllData();
        }
      })
      .catch((err) => setCacheMessage(`에러: ${err.message}`))
      .finally(() => setCachingTags(false));
  };

  const handleDayClick = (date: string) => {
    setSelectedDay(date);
    setDayDetail(null);
    setLoadingDayDetail(true);

    fetch(`${BASE_URL}/api/listening/day${buildQuery({ date })}`)
      .then((res) => res.json())
      .then((data: DayDetail) => setDayDetail(data))
      .catch((err) => setError(err.message))
      .finally(() => setLoadingDayDetail(false));
  };

  if (error) return <div>에러 발생: {error}</div>;
  if (!stats) return <div>불러오는 중...</div>;

  const fmtVal = makeFmt(metric);
  const axisFmt = (v: number) => (metric === "time" ? `${Math.round(v / 60)}h` : String(v));

  const shownTop =
    topMode === "even" && evenTop
      ? evenTop
      : topMode === "time" && timeTop
        ? timeTop
        : { artist: topArtists, track: topTracks, album: topAlbums, months: topMonths };

  return (
    <div style={{ padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>Analyse Your Music</h1>

      {/* 상단 컨트롤: 새로고침 버튼 + 기간 필터 */}
      <div style={{ marginBottom: "1rem", display: "flex", gap: "1rem", alignItems: "center" }}>
        <button onClick={handleRefresh} disabled={refreshing} style={{ padding: "0.5rem 1rem" }}>
          {refreshing ? "업데이트 중..." : "🔄 최신 스크롭 불러오기"}
        </button>

        <div style={{ position: "relative" }}>
          <button
            onClick={() => {
              setTempStart(dateRange.start ?? "");
              setTempEnd(dateRange.end ?? "");
              setFilterOpen((v) => !v);
            }}
            style={{ padding: "0.5rem 1rem" }}
          >
            📅 {dateRange.label}
          </button>

          {filterOpen && (
            <div
              style={{
                position: "absolute",
                top: "110%",
                left: 0,
                background: "white",
                border: "1px solid #ccc",
                borderRadius: 8,
                padding: "1rem",
                boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
                zIndex: 10,
                width: 320,
              }}
            >
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "0.5rem",
                  marginBottom: "1rem",
                }}
              >
                {[7, 30, 90, 180, 365].map((n) => (
                  <button
                    key={n}
                    onClick={() => {
                      setDateRange(daysAgo(n));
                      setFilterOpen(false);
                    }}
                    style={{ padding: "0.4rem" }}
                  >
                    최근 {n}일
                  </button>
                ))}
                {[2025, 2026].map((y) => (
                  <button
                    key={y}
                    onClick={() => {
                      setDateRange(yearRange(y));
                      setFilterOpen(false);
                    }}
                    style={{ padding: "0.4rem" }}
                  >
                    {y}년
                  </button>
                ))}
                <button
                  onClick={() => {
                    setDateRange(ALL_TIME);
                    setFilterOpen(false);
                  }}
                  style={{ padding: "0.4rem", color: "#c00", gridColumn: "span 2" }}
                >
                  전체 기간
                </button>
              </div>

              <hr style={{ margin: "0.5rem 0" }} />

              <label style={{ display: "block", fontSize: "0.8rem", color: "#888" }}>FROM</label>
              <input
                type="date"
                value={tempStart}
                onChange={(e) => setTempStart(e.target.value)}
                style={{ width: "100%", padding: "0.4rem", marginBottom: "0.5rem" }}
              />

              <label style={{ display: "block", fontSize: "0.8rem", color: "#888" }}>TO</label>
              <input
                type="date"
                value={tempEnd}
                onChange={(e) => setTempEnd(e.target.value)}
                style={{ width: "100%", padding: "0.4rem", marginBottom: "1rem" }}
              />

              <div style={{ display: "flex", justifyContent: "flex-end", gap: "0.5rem" }}>
                <button onClick={() => setFilterOpen(false)}>Cancel</button>
                <button
                  onClick={() => {
                    setDateRange({
                      start: tempStart || undefined,
                      end: tempEnd || undefined,
                      label: tempStart && tempEnd ? `${tempStart} ~ ${tempEnd}` : "커스텀 기간",
                    });
                    setFilterOpen(false);
                  }}
                  style={{ background: "#c00", color: "white", padding: "0.4rem 0.8rem" }}
                >
                  Apply
                </button>
              </div>
            </div>
          )}
        </div>

        <button onClick={handleFetchTagCache} disabled={cachingTags} style={{ padding: "0.5rem 1rem" }}>
          {cachingTags
            ? "태그 조회 중..."
            : `🏷️ 아티스트 태그 캐시 20명 더 불러오기${
                tagDistribution ? ` (${tagDistribution.covered_artists} / ${tagDistribution.total_artists})` : ""
              }`}
        </button>
      </div>

      {cacheMessage && <p>{cacheMessage}</p>}

      {/* 탭 바 */}
      <div style={{ display: "flex", gap: "0.5rem", borderBottom: "1px solid #ddd", marginBottom: "1.5rem" }}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: "0.6rem 1rem",
              border: "none",
              borderBottom: activeTab === tab.id ? "2px solid #333" : "2px solid transparent",
              background: "none",
              fontWeight: activeTab === tab.id ? "bold" : "normal",
              cursor: "pointer",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {refreshMessage && <p>{refreshMessage}</p>}

      {/* 치명적 에러는 탭과 무관하게 항상 상단에 노출 */}
      {validation && !validation.valid && (
        <div
          style={{
            background: "#fdd",
            border: "1px solid #c00",
            borderRadius: 8,
            padding: "1rem",
            marginBottom: "1rem",
          }}
        >
          <strong>⚠️ 데이터에 치명적인 문제가 있습니다</strong>
          <ul>
            {validation.errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Overview 탭 */}
      {activeTab === "overview" && (
        <>
          <ul>
            <li>Total Scrobbles: {stats.total_scrobbles}</li>
            <li>Unique Tracks: {stats.unique_tracks}</li>
            <li>Unique Artists: {stats.unique_artists}</li>
            <li>Unique Albums: {stats.unique_albums}</li>
            <li>First Scrobble: {stats.first_scrobble ?? "-"}</li>
            <li>Last Scrobble: {stats.last_scrobble ?? "-"}</li>
            {timeSummary && (
              <>
                <li>
                  총 청취 시간: {fmtHM(timeSummary.total_seconds)}{" "}
                  <span style={{ color: "#888", fontSize: "0.85rem" }}>
                    (스크로블 × 곡 길이 추정 · 길이를 아는 재생 {Math.round(timeSummary.coverage * 100)}% 기준)
                  </span>
                </li>
                <li>
                  하루 평균: {fmtHM(timeSummary.avg_seconds_per_day)}{" "}
                  <span style={{ color: "#888", fontSize: "0.85rem" }}>
                    ({timeSummary.days}일 기준 · 청취한 날 {timeSummary.active_days}일 평균 {fmtHM(timeSummary.avg_seconds_per_active_day)})
                  </span>
                </li>
                {timeSummary.busiest_day && (
                  <li>
                    가장 많이 들은 날: {withWeekday(timeSummary.busiest_day.date)} ({fmtHM(timeSummary.busiest_day.seconds)}, {timeSummary.busiest_day.plays}회)
                  </li>
                )}
              </>
            )}
          </ul>

          {diversity && (
            <>
              <h2>음악 소비 다양성</h2>
              <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
                {(["artist", "track", "album"] as const).map((key) => {
                  const label = { artist: "아티스트", track: "트랙", album: "앨범" }[key];
                  const m = diversity[key];
                  return (
                    <div
                      key={key}
                      style={{
                        flex: 1,
                        minWidth: 220,
                        border: "1px solid #eee",
                        borderRadius: 8,
                        padding: "1rem",
                      }}
                    >
                      <h3 style={{ marginTop: 0 }}>{label}</h3>
                      <p>다양성 점수: {(m.normalized_entropy * 100).toFixed(0)} / 100</p>
                      <p>상위 10%가 전체의 {m.top10pct_concentration}% 차지</p>
                      <p style={{ color: "#888", fontSize: "0.85rem" }}>
                        가장 많이 들은 {label}: {m.most_played.name ?? "-"} ({m.most_played.count}회)
                      </p>
                    </div>
                  );
                })}
              </div>
            </>
          )}
          <h2>청취 활동 히트맵</h2>
          <MetricToggle metric={metric} onChange={setMetric} />
          <ContributionHeatmap data={dailyData} onDayClick={handleDayClick} format={fmtVal} />
        </>
      )}

      {/* Listening 탭 */}
      {activeTab === "listening" && (
        <>
        <MetricToggle metric={metric} onChange={setMetric} />
        <h2>청취 시계</h2>
        <ListeningClock data={hourlyData} format={fmtVal} noun={metric === "time" ? "청취 시간" : "스크로블"} />

          <h2>주간 {metric === "time" ? "청취 시간" : "스크로블"}</h2>
          <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={weekdayData}>
              <defs>
                <linearGradient id="weeklyGradient" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#8884d8" stopOpacity={0.6} />
                  <stop offset="95%" stopColor="#8884d8" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" />
              <YAxis tickFormatter={axisFmt} />
              <Tooltip formatter={(v) => fmtVal(Number(v))} />
              <Area type="monotone" dataKey="count" stroke="#8884d8" strokeWidth={2} fill="url(#weeklyGradient)" />
            </AreaChart>
          </ResponsiveContainer>
          {weekdayData.length > 0 && (
            <p style={{ color: "#888" }}>
              가장 바쁜 요일: {[...weekdayData].sort((a, b) => b.count - a.count)[0].label} (
              {fmtVal([...weekdayData].sort((a, b) => b.count - a.count)[0].count)})
            </p>
          )}

          <h2>월별 청취 추이</h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={monthlyData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" />
              <YAxis tickFormatter={axisFmt} />
              <Tooltip formatter={(v) => fmtVal(Number(v))} />
              <Line type="monotone" dataKey="count" stroke="#8884d8" />
            </LineChart>
          </ResponsiveContainer>

          <h2>연도별 청취 추이</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={yearlyData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" />
              <YAxis tickFormatter={axisFmt} />
              <Tooltip formatter={(v) => fmtVal(Number(v))} />
              <Bar dataKey="count" fill="#82ca9d" />
            </BarChart>
          </ResponsiveContainer>
        </>
      )}

      {/* Music 탭 */}
      {activeTab === "music" && (
        <>
          <h2>Top 10</h2>
          <div style={{ display: "flex", gap: "0.5rem", justifyContent: "center", marginBottom: "0.5rem" }}>
            {([
              ["plays", "많이 들은 순"],
              ["time", "오래 들은 순"],
              ["even", "꾸준히 들은 순"],
            ] as const).map(([mode, label]) => (
              <button
                key={mode}
                onClick={() => setTopMode(mode)}
                style={{ padding: "0.4rem 0.9rem", fontWeight: topMode === mode ? "bold" : "normal", border: topMode === mode ? "2px solid #8884d8" : "1px solid #666" }}
              >
                {label}
              </button>
            ))}
          </div>
          {topMode === "time" && (
            <p style={{ color: "#888", fontSize: "0.85rem", textAlign: "center", marginTop: 0 }}>
              청취 시간(스크로블 횟수 × 곡 길이, 끝까지 들었다고 가정한 추정치) 순입니다. 긴 곡·긴 앨범이 위로 올라옵니다.
              {!timeTop && " 불러오는 중..."}
            </p>
          )}
          {topMode === "even" && (
            <p style={{ color: "#888", fontSize: "0.85rem", textAlign: "center", marginTop: 0 }}>
              {consMinPlays}회 이상, {consMinMonths}개월 이상에 걸쳐 들은 항목 중 월별 재생이 가장 고른 순입니다. 기준은 Consistency 탭에서 바꿀 수 있어요.
              {!evenTop && " 불러오는 중..."}
            </p>
          )}
          <div style={{ maxWidth: 980, margin: "0 auto", textAlign: "left" }}>
            {([
              ["artist", "Artists", shownTop.artist],
              ["track", "Tracks", shownTop.track],
              ["album", "Albums", shownTop.album],
            ] as [RankKind, string, TopItem[]][]).map(([kind, title, items]) => (
              <section key={kind} style={{ marginTop: "1.5rem" }}>
                <h3 style={{ fontWeight: 400, marginBottom: "0.4rem" }}>{title}</h3>
                {items.map((item, i) => {
                  const c = item.consistency;
                  const byEven = topMode === "even" && c?.evenness != null;
                  const byTime = topMode === "time" && item.seconds !== undefined;
                  return (
                    <RankRow
                      key={`${item.artist}|${item.name}`}
                      rank={i + 1}
                      item={item}
                      max={items[0]?.count ?? 1}
                      kind={kind}
                      extra={<ConsistencyLine c={c} months={shownTop.months} plays={byEven || byTime ? item.count : undefined} />}
                      barFraction={byEven ? (c?.evenness ?? 0) : byTime ? (item.seconds ?? 0) / Math.max(1, items[0]?.seconds ?? 1) : undefined}
                      barText={byEven ? `${Math.round((c?.evenness ?? 0) * 100)}%` : byTime ? fmtHM(item.seconds ?? 0) : undefined}
                    />
                  );
                })}
              </section>
            ))}
          </div>
        </>
      )}

      {/* Library 탭: Last.fm 라이브러리 같은 순위 목록과 상세 */}
      {activeTab === "library" && <Library query={buildQuery} />}

      {/* Consistency 탭: 월별 재생이 고르게 퍼진 순 / 한 시기에 몰린 순 */}
      {activeTab === "consistency" && (
        <>
          <h2>청취 날짜 편향도</h2>
          <p style={{ color: "#888", marginTop: 0, fontSize: "0.9rem" }}>
            항목을 처음 들은 달부터 지금까지를 월 단위로 나눠, 재생이 얼마나 고르게 퍼져 있는지 봅니다. 100%에 가까울수록 꾸준히,
            0%에 가까울수록 한 시기에 몰아 들은 항목입니다. 지금은 안 듣는 곡은 마지막 달들이 비어 점수가 내려갑니다.
          </p>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "center", marginBottom: "1rem" }}>
            <label>
              대상{" "}
              <select value={consCategory} onChange={(e) => setConsCategory(e.target.value as "artist" | "track" | "album")}>
                <option value="track">트랙</option>
                <option value="artist">아티스트</option>
                <option value="album">앨범</option>
              </select>
            </label>
            <label>
              정렬{" "}
              <select value={consSort} onChange={(e) => setConsSort(e.target.value as "even" | "biased")}>
                <option value="even">가장 고른 순</option>
                <option value="biased">가장 몰린 순</option>
              </select>
            </label>
            <label>
              최소 재생{" "}
              <input type="number" min={5} value={consMinPlays} style={{ width: 64 }} onChange={(e) => setConsMinPlays(Math.max(5, Number(e.target.value) || 5))} />
              회
            </label>
            <label>
              최소 기간{" "}
              <input type="number" min={2} value={consMinMonths} style={{ width: 56 }} onChange={(e) => setConsMinMonths(Math.max(2, Number(e.target.value) || 2))} />
              개월
            </label>
          </div>
          {consLoading && <p style={{ color: "#888" }}>불러오는 중...</p>}
          {consData && (
            <>
              <p style={{ color: "#888", fontSize: "0.85rem" }}>
                조건에 맞는 항목 {consData.total_candidates}개 중 상위 {consData.results.length}개 ({consData.months[0]} ~ {consData.months[consData.months.length - 1]})
              </p>
              <ol style={{ paddingLeft: "1.8rem" }}>
                {consData.results.map((item) => (
                  <li key={item.key} style={{ marginBottom: "0.7rem" }}>
                    <div style={{ display: "flex", alignItems: "center", gap: "0.8rem", flexWrap: "wrap" }}>
                      {consData.category === "artist" ? (
                        <Cover kind="artist" artist={item.name} />
                      ) : (
                        <Cover kind="album" artist={item.artist} album={consData.category === "track" ? item.album : item.name} />
                      )}
                      <div style={{ minWidth: 220, flex: 1 }}>
                        <div>
                          {item.name}
                          {item.artist && <span style={{ color: "#888" }}> - {item.artist}</span>}{" "}
                          <span style={{ color: "#888" }}>({item.plays}회)</span>
                        </div>
                        <div style={{ color: "#888", fontSize: "0.8rem" }}>
                          {item.first_month} 시작 · {item.active_months}/{item.months}개월 청취 · 최다 {item.peak_month} ({Math.round(item.peak_share * 100)}%)
                          {item.months_since_last >= 1 ? ` · 마지막 청취 ${item.months_since_last}개월 전` : ""}
                        </div>
                      </div>
                      <Sparkline monthly={item.monthly} months={consData.months} width={Math.min(180, consData.months.length * 6)} height={28} />
                      <strong style={{ width: 56, textAlign: "right" }}>{item.evenness === null ? "-" : `${Math.round(item.evenness * 100)}%`}</strong>
                    </div>
                  </li>
                ))}
              </ol>
              {consData.results.length === 0 && <p style={{ color: "#888" }}>조건에 맞는 항목이 없습니다. 최소 재생·기간을 낮춰 보세요.</p>}
            </>
          )}
        </>
      )}

      {/* Discovery 탭 */}
      {activeTab === "discovery" && discoverySummary && (
        <>
          <h2>새로 발견한 음악</h2>
          <ul>
            <li>총 신규 트랙: {discoverySummary.track.total_new}개</li>
            <li>총 신규 아티스트: {discoverySummary.artist.total_new}명</li>
            <li>총 신규 앨범: {discoverySummary.album.total_new}개</li>
          </ul>

          <h3>월별 신규 트랙 수</h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart
              data={discoverySummary.track.months.map((m, i) => ({
                period: m,
                newTracks: discoverySummary.track.counts[i],
              }))}
            >
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="period" tick={{ fontSize: 11 }} angle={-45} textAnchor="end" height={60} />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="newTracks" stroke="#8884d8" name="신규 트랙 수" />
            </LineChart>
          </ResponsiveContainer>

          <h3>최근 발견한 곡</h3>
          <ol style={{ paddingLeft: "1.6rem" }}>
            {discoveryTimeline.map((item, i) => (
              <li key={i} style={{ marginBottom: "0.5rem" }}>
                <div style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
                  <Cover kind="album" artist={item.artist} album={item.album} />
                  <span>
                    {item.name}
                    {item.artist && <span style={{ color: "#888" }}> - {item.artist}</span>}{" "}
                    <span style={{ color: "#888" }}>({item.first_listened})</span>
                  </span>
                </div>
              </li>
            ))}
          </ol>
        </>
      )}

      {/* Taste 탭 */}
      {activeTab === "taste" && (
        <>
          {tagDistribution && (
            <>
              <h2>
                장르/태그 분포{" "}
                <span style={{ fontSize: "0.8rem", color: "#888" }}>
                  ({tagDistribution.covered_artists} / {tagDistribution.total_artists} 아티스트 기준)
                </span>
              </h2>
              <ResponsiveContainer width="100%" height={400}>
                <BarChart data={tagDistribution.tags} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" />
                  <YAxis dataKey="tag" type="category" width={100} />
                  <Tooltip />
                  <Bar dataKey="score" fill="#ff7f50" />
                </BarChart>
              </ResponsiveContainer>
            </>
          )}

          {tagEvolution && tagEvolution.periods.length > 0 && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
                <h2 style={{ margin: 0 }}>취향 변화 (월별 장르 트렌드)</h2>
                <div>
                  <button
                    onClick={() => setEvolutionMode("fixed")}
                    style={{
                      padding: "0.3rem 0.7rem",
                      fontWeight: evolutionMode === "fixed" ? "bold" : "normal",
                      background: evolutionMode === "fixed" ? "#eee" : "white",
                    }}
                  >
                    전체 기간 기준
                  </button>
                  <button
                    onClick={() => setEvolutionMode("dynamic")}
                    style={{
                      padding: "0.3rem 0.7rem",
                      fontWeight: evolutionMode === "dynamic" ? "bold" : "normal",
                      background: evolutionMode === "dynamic" ? "#eee" : "white",
                    }}
                  >
                    월별 실제 순위
                  </button>
                </div>
              </div>

              {evolutionMode === "fixed" ? (
                <ResponsiveContainer width="100%" height={400}>
                  <AreaChart
                    data={tagEvolution.periods.map((period, i) => {
                      const row: Record<string, string | number> = { period };
                      tagEvolution.series.forEach((s) => {
                        row[s.tag] = s.values[i] ?? 0;
                      });
                      return row;
                    })}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="period" tick={{ fontSize: 11 }} angle={-45} textAnchor="end" height={60} />
                    <YAxis />
                    <Tooltip content={<SortedTagTooltip />} />
                    {tagEvolution.series.map((s, i) => {
                      const color = ["#8884d8", "#82ca9d", "#ff7f50", "#ffc658", "#a4de6c", "#d0ed57", "#d62728", "#9467bd"][
                        i % 8
                      ];
                      return (
                        <Area
                          key={s.tag}
                          type="monotone"
                          dataKey={s.tag}
                          stackId="1"
                          stroke={color}
                          fill={color}
                          fillOpacity={0.6}
                        />
                      );
                    })}
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <ResponsiveContainer width="100%" height={400}>
                  <LineChart
                    data={tagEvolution.periods.map((period, i) => {
                      const row: Record<string, string | number | null> = { period };
                      tagEvolution.series.forEach((s) => {
                        row[s.tag] = s.values[i];
                      });
                      return row;
                    })}
                  >
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="period" tick={{ fontSize: 11 }} angle={-45} textAnchor="end" height={60} />
                    <YAxis />
                    <Tooltip content={<SortedTagTooltip />} />
                    {tagEvolution.series.map((s, i) => (
                      <Line
                        key={s.tag}
                        type="monotone"
                        dataKey={s.tag}
                        stroke={["#8884d8", "#82ca9d", "#ff7f50", "#ffc658", "#a4de6c", "#d0ed57", "#d62728", "#9467bd"][i % 8]}
                        connectNulls={false}
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              )}
            </>
          )}
<br></br>
          <h2>
            아티스트별 태그 {totalTagsPages && `(${artistTags.length} / ${stats.unique_artists})`}
          </h2>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ textAlign: "left", borderBottom: "1px solid #ccc" }}>
                <th style={{ padding: "0.5rem" }}>아티스트</th>
                <th style={{ padding: "0.5rem" }}>재생 횟수</th>
                <th style={{ padding: "0.5rem" }}>태그</th>
              </tr>
            </thead>
            <tbody>
              {artistTags.map((a, i) => (
                <tr key={i} style={{ borderBottom: "1px solid #eee" }}>
                  <td style={{ padding: "0.5rem" }}>{a.artist}</td>
                  <td style={{ padding: "0.5rem" }}>{a.play_count}</td>
                  <td style={{ padding: "0.5rem" }}>{a.tags.join(", ") || "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>

          {totalTagsPages !== null && tagsPage < totalTagsPages && (
            <button
              onClick={() => loadArtistTagsPage(tagsPage + 1)}
              disabled={loadingTags}
              style={{ marginTop: "1rem", padding: "0.5rem 1rem" }}
            >
              {loadingTags ? "불러오는 중..." : "더 보기"}
            </button>
          )}

          {totalTagsPages !== null && tagsPage >= totalTagsPages && artistTags.length > 0 && (
            <p style={{ marginTop: "1rem", color: "#888" }}>전체 아티스트를 다 불러왔습니다.</p>
          )}
        </>
      )}

      {/* Data 탭 */}
      {activeTab === "data" && (
        <>
          <h2 style={{ marginTop: "2rem" }}>AI 분석용 프롬프트 생성</h2>
          <p style={{ color: "#888", fontSize: "0.9rem" }}>
            {promptKind === "all"
              ? `지금 선택된 기간(${dateRange.label}) 기준으로 청취 데이터를 정리한 프롬프트를 만들어요.`
              : `${
                  { month: "고른 달을 직전 달과", week: "고른 주를 직전 주와", year: "고른 해를 전년과" }[promptKind]
                } 비교한 프롬프트를 만들어요. (위쪽 날짜 범위와 상관없이 전체 기록에서 계산됩니다)`}{" "}
            복사해서 ChatGPT나 Claude 같은 AI에게 붙여넣고 취향 분석을 물어보면 됩니다.
          </p>
          <div style={{ display: "flex", gap: "1rem", alignItems: "center", marginBottom: "0.75rem", flexWrap: "wrap" }}>
            {([["all", "전체 기간"], ["year", "연간"], ["month", "월간"], ["week", "주간"]] as const).map(([kind, label]) => (
              <label key={kind} style={{ cursor: "pointer" }}>
                <input
                  type="radio"
                  name="promptKind"
                  checked={promptKind === kind}
                  onChange={() => setPromptKind(kind)}
                />{" "}
                {label}
              </label>
            ))}
            {promptKind !== "all" && (
              <select value={periodKey} onChange={(e) => setPeriodKey(e.target.value)} style={{ padding: "0.3rem" }}>
                {periodOptions.map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label} ({o.scrobbles.toLocaleString()}회{o.partial ? " · 일부 기간" : ""})
                  </option>
                ))}
              </select>
            )}
          </div>
          <button
            onClick={handleGeneratePrompt}
            disabled={generatingPrompt || (promptKind !== "all" && !periodKey)}
            style={{ padding: "0.5rem 1rem", marginBottom: "1rem" }}
          >
            {generatingPrompt ? "생성 중..." : "📋 프롬프트 생성"}
          </button>
          {promptNote && <p style={{ color: "#888", fontSize: "0.85rem", margin: "0 0 0.75rem" }}>{promptNote}</p>}

          {aiPrompt && (
            <div>
              <textarea
                readOnly
                value={aiPrompt}
                style={{
                  width: "100%",
                  height: 400,
                  padding: "0.75rem",
                  fontFamily: "monospace",
                  fontSize: "0.8rem",
                  whiteSpace: "pre-wrap",
                  boxSizing: "border-box",
                }}
              />
              <button onClick={handleCopyPrompt} style={{ padding: "0.5rem 1rem", marginTop: "0.5rem" }}>
                {copied ? "복사됨!" : "📋 클립보드에 복사"}
              </button>
            </div>
          )}

          <h2>데이터 상태</h2>

          <div style={{ marginBottom: "1.5rem" }}>
            <button
              onClick={handleInvalidateAliasCache}
              disabled={invalidating}
              style={{ padding: "0.5rem 1rem" }}
            >
              {invalidating ? "처리 중..." : "🔄 매핑된 아티스트 캐시 초기화"}
            </button>
            {invalidateMessage && (
              <p style={{ marginTop: "0.5rem", color: "#666" }}>{invalidateMessage}</p>
            )}
          </div>

          {validation && (
            <>
              <p>총 데이터 행 수: {validation.total_rows}</p>

              {validation.valid && validation.warnings.length > 0 && (
                <div
                  style={{
                    background: "#fff3cd",
                    border: "1px solid #e0a800",
                    borderRadius: 8,
                    padding: "1rem",
                    marginBottom: "1rem",
                  }}
                >
                  <strong>⚠️ 데이터 검증 경고 ({validation.warnings.length}건)</strong>
                  <ul>
                    {validation.warnings.map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                  </ul>
                </div>
              )}

              {validation.valid && validation.warnings.length === 0 && (
                <p style={{ color: "#2a2" }}>✅ 검증 통과, 문제 없음</p>
              )}
            </>
          )}
        </>
      )}

      {selectedDay && (
        <DayDetailModal
          detail={dayDetail}
          loading={loadingDayDetail}
          onClose={() => setSelectedDay(null)}
        />
      )}
    </div>
  );
}

export default App;