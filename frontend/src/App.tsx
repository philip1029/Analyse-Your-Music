import { useEffect, useState, useCallback, useRef, type CSSProperties } from "react";
import { BASE_URL } from "./config";
import { Library, type LibraryRequest, type LibraryTarget, type SortMode } from "./Library";
import { ShareButton, ShareProvider } from "./Share";
import { CatStat, OverviewCards } from "./OverviewCards";
import { DecadeCard } from "./DecadeCard";
import { TopCards } from "./TopCards";
import { FunFactCard } from "./FunFactCard";
import { TagDistributionCard } from "./TagCompare";
import { RaceTab } from "./Race";
import { DiscoveryList } from "./DiscoveryList";
import { CAT, type Cat } from "./theme";
import { ALL_TIME, PeriodBar } from "./PeriodBar";
import { Reveal, Skeleton, prefersReducedMotion, useInView } from "./motion";
import { RankRow } from "./RankRow";
import { RefreshBar } from "./RefreshBar";
import { SearchBox } from "./Search";
import { AppleFiles } from "./AppleFiles";
import { makeFmt, withWeekday, type Metric } from "./format";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  AreaChart,
  Area,
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
  covered_plays: number;
  total_plays: number;
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

type TabId = "overview" | "listening" | "music" | "discovery" | "taste" | "race" | "data";

// 한 페이지의 구역들. 위쪽 이동 버튼과 구역 제목이 이 목록을 함께 쓴다.
const TABS: { id: TabId; label: string; icon: string; num: string }[] = [
  { id: "overview", label: "요약", icon: "📊", num: "01" },
  { id: "listening", label: "청취", icon: "🕘", num: "02" },
  { id: "music", label: "음악", icon: "🎵", num: "03" },
  { id: "discovery", label: "발견", icon: "🔭", num: "04" },
  { id: "taste", label: "취향", icon: "🎨", num: "05" },
  { id: "race", label: "레이스", icon: "🏁", num: "06" },
  { id: "data", label: "데이터", icon: "🗂", num: "07" },
];

// 차트 공용 모양 (recharts 기본색 대신 앱 색을 쓴다)
const GRID_STROKE = "rgba(255,255,255,0.08)";
const AXIS_TICK = { fill: "rgba(245,245,247,0.5)", fontSize: 12 };
const TIP = {
  contentStyle: { background: "#1b1b1f", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 12, color: "#f5f5f7", boxShadow: "0 10px 30px rgba(0,0,0,0.5)" },
  labelStyle: { color: "rgba(245,245,247,0.7)", fontWeight: 700 },
  itemStyle: { color: "#f5f5f7" },
  cursor: { stroke: "rgba(255,255,255,0.2)", fill: "rgba(255,255,255,0.05)" },
};
const TAG_COLORS = ["#c490ff", "#61d4b6", "#469df8", "#ffcace", "#fa233b", "#ffb86b", "#9be564", "#ff7eb6"];

const hourKo = (h: number) => `${h < 12 ? "오전" : "오후"} ${h % 12 === 0 ? 12 : h % 12}시`;
const peakOf = (xs: ChartPoint[]) => (xs.length ? xs.reduce((a, b) => (b.count > a.count ? b : a)) : null);

// 선택한 기간이 한 해 / 한 달 / 월~일 한 주 하나와 정확히 같으면 그 종류와 기준값(anchor)을 돌려준다
function detectPeriod(range: { start?: string; end?: string }): { kind: "year" | "month" | "week"; anchor: string } | null {
  const { start, end } = range;
  if (!start || !end) return null;
  const sm = /^(\d{4})-(\d{2})-(\d{2})$/.exec(start);
  const em = /^(\d{4})-(\d{2})-(\d{2})$/.exec(end);
  if (!sm || !em) return null;
  const [sy, smo, sd] = [Number(sm[1]), Number(sm[2]), Number(sm[3])];
  const [ey, emo, ed] = [Number(em[1]), Number(em[2]), Number(em[3])];
  if (sy === ey && smo === 1 && sd === 1 && emo === 12 && ed === 31) return { kind: "year", anchor: String(sy) };
  const lastDay = new Date(Date.UTC(ey, emo, 0)).getUTCDate();
  if (sy === ey && smo === emo && sd === 1 && ed === lastDay) return { kind: "month", anchor: `${sy}-${sm[2]}` };
  const startMs = Date.UTC(sy, smo - 1, sd);
  if (new Date(startMs).getUTCDay() === 1 && Date.UTC(ey, emo - 1, ed) - startMs === 6 * 86400000) return { kind: "week", anchor: start };
  return null;
}

// Data 탭: 왼쪽 정렬한 카드(패널) 레이아웃
// 업데이트 배너에 붙는 SemVer 변화 종류
const BUMP_LABEL: Record<string, string> = {
  major: "호환이 깨지는 큰 변경",
  minor: "기능 추가",
  patch: "버그 수정",
  pre: "정식 버전 쪽으로",
};

const DATA_PANEL: CSSProperties = { background: "var(--surface)", border: "1px solid var(--line)", borderRadius: "var(--r)", padding: "1.3rem 1.4rem" };
const DATA_TITLE: CSSProperties = { margin: "0 0 0.8rem", fontSize: "1.15rem", fontWeight: 800 };
const DATA_LABEL: CSSProperties = { display: "block", fontSize: "0.85rem", color: "var(--text-3)", margin: "0 0 0.3rem" };
const DATA_INPUT: CSSProperties = { width: "100%", marginBottom: "0.9rem" };

// 횟수 / 시간 전환 버튼 (시간 = 스크로블 횟수 x 곡 길이, 끝까지 들었다고 가정한 추정치)
function MetricToggle({ metric, onChange }: { metric: Metric; onChange: (m: Metric) => void }) {
  return (
    <div style={{ display: "flex", gap: "0.7rem", alignItems: "center", flexWrap: "wrap", margin: "0.4rem 0 0.8rem" }}>
      <div className="aym-seg" role="group" aria-label="보기 기준">
        {([
          ["plays", "재생 횟수"],
          ["time", "청취 시간"],
        ] as const).map(([m, label]) => (
          <button key={m} aria-pressed={metric === m} onClick={() => onChange(m)}>
            {label}
          </button>
        ))}
      </div>
      {metric === "time" && <span className="aym-muted" style={{ fontSize: "0.8rem" }}>스크로블 횟수 × 곡 길이 (끝까지 들었다고 가정한 추정치)</span>}
    </div>
  );
}

// 구역 제목줄: "01 · 요약" (오른쪽에 버튼을 둘 수 있다)
function Eyebrow({ id, actions }: { id: TabId; actions?: React.ReactNode }) {
  const t = TABS.find((x) => x.id === id)!;
  return (
    <div className="aym-eyebrow">
      {t.num} <span>·</span> {t.label}
      {actions && <div className="aym-actions">{actions}</div>}
    </div>
  );
}

// 문장 해설 + 핵심 수치 칩 (구역마다 같은 모양)
function Lede({ children, small }: { children: React.ReactNode; small?: boolean }) {
  return <p className={`aym-lede${small ? " sm" : ""}`}>{children}</p>;
}
function Facts({ items }: { items: { label: string; value: string; sub?: string }[] }) {
  return (
    <div className="aym-facts">
      {items.map((f) => (
        <div className="aym-fact" key={f.label}>
          <small>{f.label}</small>
          <b>
            {f.value}
            {f.sub && <em>{f.sub}</em>}
          </b>
        </div>
      ))}
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

  // 민트 계열 4단계(진할수록 많이 들은 날). 0 은 거의 보이지 않는 회색 칸
  const getColor = (count: number) => {
    if (count === 0) return "rgba(255,255,255,0.07)";
    const ratio = count / maxCount;
    if (ratio < 0.25) return "#1d4a42";
    if (ratio < 0.5) return "#2b8473";
    if (ratio < 0.75) return "#45b99d";
    return "#86f0d2";
  };
  const [panelRef, seen] = useInView<HTMLDivElement>();

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
    <div ref={panelRef} className="aym-panel" style={{ marginBottom: "0.9rem" }}>
      <h4 style={{ margin: "0 0 0.5rem 0", color: "var(--text-2)" }}>{year}</h4>
      <div style={{ overflowX: "auto" }}>
        <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", minWidth: 640, height: "auto", display: "block" }}>
          {monthLabels.map((m, i) => (
            <text key={i} x={m.x} y={10} fontSize={10} fill="rgba(245,245,247,0.4)">
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
                  className={inYear && seen ? "aym-cell" : undefined}
                  style={{ cursor: inYear ? "pointer" : "default", opacity: inYear && !seen ? 0 : undefined, animationDelay: seen ? `${wi * 9 + di * 12}ms` : undefined }}
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

  // 화면에 보이는 순간부터 0시 → 23시 순서로 쐐기들이 바깥으로 자라난다 (값이 바뀌면 다시 펼쳐진다). t: 0 → 1
  const [viewRef, seen] = useInView<SVGSVGElement>();
  const [t, setT] = useState(() => (prefersReducedMotion() ? 1 : 0));
  const dataKey = data.map((d) => d.count).join(",");
  useEffect(() => {
    if (!seen) return;
    if (prefersReducedMotion()) {
      setT(1);
      return;
    }
    let raf = 0;
    const start = performance.now();
    const tick = (now: number) => {
      const p = Math.min(1, (now - start) / 1500);
      setT(p);
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [seen, dataKey]);

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
    <div ref={containerRef} style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", gap: "2.5rem", flexWrap: "wrap" }}>
      <svg ref={viewRef} width={size} height={size}>
        {data.map((d, h) => {
          const startAngle = h * 15 + gapDeg / 2;
          const endAngle = (h + 1) * 15 - gapDeg / 2;
          const ratio = d.count / maxCount;
          // 쐐기마다 시작 시점이 조금씩 늦다 (전체의 45% 동안 차례로 출발, 각자 55% 동안 자란다)
          const local = Math.min(1, Math.max(0, (t - (h / 24) * 0.45) / 0.55));
          const grown = 1 - Math.pow(1 - local, 3);
          const rOuter = rInner + (rOuterMax - rInner) * ratio * grown;
          const isHovered = tooltip?.hour === h;

        return (
          <g
            key={h}
            onMouseMove={(e) => handleMove(e, h)}
            onMouseLeave={() => setTooltip(null)}
            style={{ cursor: "pointer" }}
          >
            <path d={describeWedge(rOuterMax, startAngle, endAngle)} fill={isHovered ? "rgba(255,255,255,0.14)" : "rgba(255,255,255,0.07)"} opacity={Math.min(1, t * 4)} />
            {d.count > 0 && (
              <path
                d={describeWedge(rOuter, startAngle, endAngle)}
                fill={interpolateColor("#2c4a73", "#6db2ff", ratio)}
                stroke={isHovered ? "#fff" : "none"}
                strokeWidth={isHovered ? 1.5 : 0}
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
        <p style={{ color: "var(--text-3)", margin: "0 0 4px 0", fontSize: "0.85rem" }}>가장 붐비는 시간대</p>
        <p className="num" style={{ fontSize: "2rem", fontWeight: 800, margin: "0 0 1.2rem 0" }}>
          {formatHourKorean(busiestHour)}
        </p>
        <p style={{ color: "var(--text-3)", margin: "0 0 4px 0", fontSize: "0.85rem" }}>가장 바쁜 시간대의 {noun}</p>
        <p className="num" style={{ fontSize: "2rem", fontWeight: 800, margin: 0 }}>{format(maxCount)}</p>
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
        background: "Canvas",
        color: "CanvasText",
        border: "1px solid rgba(128,128,128,0.45)",
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
        background: "rgba(0,0,0,0.6)",
        backdropFilter: "blur(8px)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="aym-rise"
        style={{
          background: "#18181b",
          color: "var(--text)",
          border: "1px solid var(--line)",
          borderRadius: 26,
          boxShadow: "0 30px 80px rgba(0,0,0,0.6)",
          padding: "1.6rem",
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
                <tr style={{ textAlign: "left", borderBottom: "1px solid var(--line)", color: "var(--text-3)" }}>
                  <th style={{ padding: "0.3rem" }}>시각</th>
                  <th style={{ padding: "0.3rem" }}>아티스트</th>
                  <th style={{ padding: "0.3rem" }}>트랙</th>
                </tr>
              </thead>
              <tbody>
                {detail.tracks.map((t, i) => (
                  <tr key={i} style={{ borderBottom: "1px solid var(--line)" }}>
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

const handleGeneratePrompt = () => {
  setGeneratingPrompt(true);
  setPromptNote(null);
  const url =
    promptPeriod && compareWithPrev
      ? `${BASE_URL}/api/ai-prompt/period?period=${promptPeriod.kind}&anchor=${encodeURIComponent(promptPeriod.anchor)}`
      : `${BASE_URL}/api/ai-prompt${buildQuery()}`;
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
  const [discoveryCat, setDiscoveryCat] = useState<Cat>("track");
  // Music·Discovery 에서 항목을 누르면 Library 탭의 상세 페이지로 이동한다
  const [libraryRequest, setLibraryRequest] = useState<LibraryRequest | null>(null);
  const openInLibrary = (target: LibraryTarget) => {
    setLibraryRequest({ id: Date.now(), target });
    goTo("music");
  };
  const openListInLibrary = (category: Cat, sort: SortMode) => {
    setLibraryRequest({ id: Date.now(), list: { category, sort } });
    goTo("music");
  };

  const [invalidating, setInvalidating] = useState(false);
  const [invalidateMessage, setInvalidateMessage] = useState<string | null>(null);

  const [configStatus, setConfigStatus] = useState<{ has_api_key: boolean; username: string; apple_dir?: string; apple_files?: Record<string, boolean> } | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [usernameInput, setUsernameInput] = useState("");
  const [appleDirInput, setAppleDirInput] = useState("");
  const [savingConfig, setSavingConfig] = useState(false);
  const [configMessage, setConfigMessage] = useState<string | null>(null);

  const [installingDeps, setInstallingDeps] = useState(false);
  const [installMessage, setInstallMessage] = useState<string | null>(null);

  // 한 페이지 구조: 구역이 화면 근처에 오면 그때 내용을 불러오고 그린다 (무거운 구역을 처음부터 다 받지 않도록).
  // reached = 한 번이라도 가까워진 구역, current = 지금 보고 있는 구역(위쪽 이동 버튼 강조용)
  const [reached, setReached] = useState<Set<TabId>>(() => new Set<TabId>(["overview"]));
  const [current, setCurrent] = useState<TabId>("overview");
  const reach = useCallback((id: TabId) => setReached((prev) => (prev.has(id) ? prev : new Set(prev).add(id))), []);
  const goTo = useCallback(
    (id: TabId) => {
      reach(id);
      const go = (behavior: ScrollBehavior) => document.getElementById(id)?.scrollIntoView({ behavior, block: "start" });
      go("smooth");
      // 도착한 구역의 내용이 늦게 채워지면 위치가 밀리므로, 아직 그 근처에 있을 때만 두 번 바로잡는다
      const fix = () => {
        const top = document.getElementById(id)?.getBoundingClientRect().top;
        if (top !== undefined && Math.abs(top) < 700) go("auto");
      };
      window.setTimeout(fix, 700);
      window.setTimeout(fix, 1600);
    },
    [reach]
  );
  const overviewReached = reached.has("overview");
  const listeningReached = reached.has("listening");
  const musicReached = reached.has("music");
  const discoveryReached = reached.has("discovery");
  const tasteReached = reached.has("taste");
  const raceReached = reached.has("race");
  const dataReached = reached.has("data");

  const [dateRange, setDateRange] = useState<DateRange>(ALL_TIME);

  // AI 프롬프트는 위쪽 기간 선택을 그대로 쓴다. 한 해/한 달/월~일 한 주를 고른 경우에는 직전 기간과 비교하는 프롬프트도 만들 수 있다.
  const [compareWithPrev, setCompareWithPrev] = useState(true);
  const [promptNote, setPromptNote] = useState<string | null>(null);
  const promptPeriod = detectPeriod(dateRange);

  useEffect(() => {
    setAiPrompt(null);
    setPromptNote(null);
  }, [dateRange, compareWithPrev]);


  const [stats, setStats] = useState<Stats | null>(null);
  const [hourlyData, setHourlyData] = useState<ChartPoint[]>([]);
  const [weekdayData, setWeekdayData] = useState<ChartPoint[]>([]);
  const [monthlyData, setMonthlyData] = useState<ChartPoint[]>([]);
  const [yearlyData, setYearlyData] = useState<ChartPoint[]>([]);
  const [validation, setValidation] = useState<ValidationResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [tagDistribution, setTagDistribution] = useState<TagDistribution | null>(null);
  const [tagEvolution, setTagEvolution] = useState<TagEvolution | null>(null);
  const [evolutionMode, setEvolutionMode] = useState<"fixed" | "dynamic">("dynamic");

  const [diversity, setDiversity] = useState<Diversity | null>(null);

  const [artistTags, setArtistTags] = useState<ArtistTagResult[]>([]);
  const [tagsPage, setTagsPage] = useState(1);
  const [totalTagsPages, setTotalTagsPages] = useState<number | null>(null);
  const [loadingTags, setLoadingTags] = useState(false);
  const tagsRequest = useRef(0);   // 날짜 범위가 빨리 바뀔 때 늦게 도착한 옛 응답이 덮어쓰지 않도록

  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);

  const [cachingTags, setCachingTags] = useState(false);
  const [cacheMessage, setCacheMessage] = useState<string | null>(null);

  const [updateInfo, setUpdateInfo] = useState<{
    update_available: boolean;
    local_version?: string | null;
    remote_version?: string | null;
    bump?: "major" | "minor" | "patch" | "pre" | null;
    remote_sha?: string;
    remote_message?: string;
  } | null>(null);
  const [updateDismissed, setUpdateDismissed] = useState(false);
  const [applyingUpdate, setApplyingUpdate] = useState(false);
  const [updateApplyMessage, setUpdateApplyMessage] = useState<string | null>(null);

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
      const id = ++tagsRequest.current;
      setLoadingTags(true);
      const qs = buildQuery({ page, page_size: 20 });
      fetch(`${BASE_URL}/api/taste/artists${qs}`)
        .then((res) => res.json())
        .then((data: ArtistTagsPage) => {
          if (id !== tagsRequest.current) return;
          if (!Array.isArray(data.artists)) return;   // {"error": ...} 응답이면 기존 목록을 그대로 둔다
          setArtistTags((prev) => (page === 1 ? data.artists : [...prev, ...data.artists]));
          setTagsPage(data.page);
          setTotalTagsPages(data.total_pages);
        })
        .catch((err) => id === tagsRequest.current && setError(err.message))
        .finally(() => id === tagsRequest.current && setLoadingTags(false));
    },
    [buildQuery]
  );

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

    fetch(`${BASE_URL}/api/diversity${qs}`)
      .then((res) => res.json())
      .then(setDiversity)
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/validate`)
      .then((res) => res.json())
      .then(setValidation)
      .catch((err) => setError(err.message));
  }, [buildQuery]);

  useEffect(() => {
    loadAllData();
  }, [loadAllData]);

  // 무거운 취향·발견 데이터는 그 구역이 가까워졌을 때만 받는다 (페이지를 처음 열 때 한꺼번에 받으면 느려진다). 태그 현황은 데이터 구역에서도 쓴다.
  useEffect(() => {
    if (!tasteReached && !dataReached) return;
    fetch(`${BASE_URL}/api/taste/tag-distribution${buildQuery()}`)
      .then((res) => res.json())
      .then(setTagDistribution)
      .catch((err) => setError(err.message));
  }, [tasteReached, dataReached, buildQuery]);

  useEffect(() => {
    if (!tasteReached) return;
    fetch(`${BASE_URL}/api/taste/evolution${buildQuery({ mode: evolutionMode })}`)
      .then((res) => res.json())
      .then(setTagEvolution)
      .catch((err) => setError(err.message));
  }, [tasteReached, buildQuery, evolutionMode]);

  useEffect(() => {
    if (!discoveryReached) return;
    fetch(`${BASE_URL}/api/discovery/summary${buildQuery()}`)
      .then((res) => res.json())
      .then(setDiscoverySummary)
      .catch((err) => setError(err.message));
  }, [discoveryReached, buildQuery]);

  // 구역이 화면 근처(위아래 700px)에 오면 불러오기 시작한다. 구역은 첫 데이터가 온 뒤에야 화면에 생긴다.
  const hasStats = stats !== null;
  useEffect(() => {
    if (!hasStats) return;
    const els = TABS.map((t) => document.getElementById(t.id)).filter((el): el is HTMLElement => el !== null);
    const io = new IntersectionObserver((entries) => entries.forEach((e) => e.isIntersecting && reach(e.target.id as TabId)), { rootMargin: "700px 0px 700px 0px" });
    els.forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [hasStats, reach]);

  // 스크롤하면 지금 보는 구역을 위쪽 이동 버튼에서 켠다
  useEffect(() => {
    if (!hasStats) return;
    const spy = () => {
      const y = window.innerHeight * 0.32;
      let cur: TabId = TABS[0].id;
      for (const t of TABS) {
        const el = document.getElementById(t.id);
        if (el && el.getBoundingClientRect().top <= y) cur = t.id;
      }
      if (window.innerHeight + window.scrollY >= document.documentElement.scrollHeight - 4) cur = TABS[TABS.length - 1].id;
      setCurrent(cur);
    };
    spy();
    window.addEventListener("scroll", spy, { passive: true });
    window.addEventListener("resize", spy);
    return () => {
      window.removeEventListener("scroll", spy);
      window.removeEventListener("resize", spy);
    };
  }, [hasStats]);

  // 켜진 버튼이 좁은 화면에서 줄 밖에 있으면 보이는 위치로 옮긴다 (페이지 전체가 아니라 버튼 줄만 움직인다)
  useEffect(() => {
    document.querySelectorAll<HTMLElement>(".aym-sections, .aym-dock").forEach((box) => {
      const on = box.querySelector<HTMLElement>("a.on");
      if (on && box.scrollWidth > box.clientWidth) box.scrollTo({ left: on.offsetLeft - (box.clientWidth - on.clientWidth) / 2, behavior: "smooth" });
    });
  }, [current]);

  useEffect(() => {
    fetch(`${BASE_URL}/api/update-check`)
      .then((res) => res.json())
      .then((data) => {
        if (data.checked) setUpdateInfo(data);
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetch(`${BASE_URL}/api/config`)
      .then((res) => res.json())
      .then((data) => {
        setConfigStatus(data);
        setUsernameInput(data.username || "");
        setAppleDirInput(data.apple_dir || "");
      })
      .catch(() => {});
  }, []);

  // Taste 탭을 열 때, 그리고 날짜 범위가 바뀔 때 1쪽부터 다시 불러온다 (이전 목록은 새 응답이 올 때까지 그대로 둔다).
  // 같은 범위로 탭만 다시 열면 이미 불러온 목록("더 보기" 포함)을 그대로 쓴다.
  const tagsLoadedFor = useRef<typeof loadArtistTagsPage | null>(null);
  useEffect(() => {
    if (!tasteReached || tagsLoadedFor.current === loadArtistTagsPage) return;
    tagsLoadedFor.current = loadArtistTagsPage;
    loadArtistTagsPage(1);
  }, [tasteReached, loadArtistTagsPage]);

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

  const handleSaveConfig = () => {
    setSavingConfig(true);
    setConfigMessage(null);

    fetch(`${BASE_URL}/api/config`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ api_key: apiKeyInput || null, username: usernameInput || null, apple_dir: appleDirInput }),
    })
      .then((res) => res.json())
      .then((data) => {
        if (data.error) {
          setConfigMessage(`저장하지 못했어요: ${data.error}`);
          return;
        }
        setConfigStatus(data);
        setApiKeyInput("");
        setAppleDirInput(data.apple_dir || "");
        setConfigMessage("저장했어요.");
      })
      .catch((err) => setConfigMessage(`에러: ${err.message}`))
      .finally(() => setSavingConfig(false));
  };

  const handleInstallDeps = () => {
    setInstallingDeps(true);
    setInstallMessage(null);

    fetch(`${BASE_URL}/api/install-deps`, { method: "POST" })
      .then((res) => res.json())
      .then((data: { pip: { success: boolean }; npm: { success: boolean } }) => {
        const pipOk = data.pip.success;
        const npmOk = data.npm.success;
        setInstallMessage(
          `${pipOk ? "✅" : "❌"} 백엔드 의존성 · ${npmOk ? "✅" : "❌"} 프론트엔드 의존성` +
            (pipOk && npmOk ? " — 설치 완료" : " — 자세한 내용은 서버를 실행 중인 터미널을 확인하세요.")
        );
      })
      .catch((err) => setInstallMessage(`에러: ${err.message}`))
      .finally(() => setInstallingDeps(false));
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
          // 아티스트 표기 통일 결과
          const arts = data.artists as { error?: string; changed_rows?: number } | null | undefined;
          if (arts?.error) {
            parts.push(`아티스트 통일 실패: ${arts.error}`);
          } else if (arts?.changed_rows) {
            parts.push(`아티스트 표기 통일 ${arts.changed_rows}행`);
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
          // 새 아티스트 태그 조회 결과
          const tagRes = data.tags as { error?: string; fetched?: number; remaining?: number } | null | undefined;
          if (tagRes?.error) {
            parts.push(`태그 조회 실패: ${tagRes.error}`);
          } else if (tagRes?.fetched) {
            parts.push(`아티스트 태그 ${tagRes.fetched}명 추가${tagRes.remaining ? ` · 남은 ${tagRes.remaining}명은 다음에` : ""}`);
          }
          // 새 앨범 발매연도(Music by decade)는 백그라운드로 채워지므로 시작하지 못했을 때만 알린다
          const yearRes = data.album_years as { error?: string } | null | undefined;
          if (yearRes?.error) {
            parts.push(`앨범 연도 조회를 시작하지 못했어요: ${yearRes.error}`);
          }
          setRefreshMessage(
            `업데이트 완료!${parts.length ? ` (${parts.join(" · ")})` : ""} 잠시 후 새로고침됩니다...`
          );
          // 정리된 행이 있거나 전처리·제목 통일이 실패했을 때는 결과를 읽을 시간을 더 준다.
          const needsTime = Boolean(pre?.error || pre?.removed || arts?.error || arts?.changed_rows || titles?.error || titles?.tracks || titles?.albums || durs?.error);
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

  const handleApplyUpdate = () => {
    setApplyingUpdate(true);
    setUpdateApplyMessage(null);

    fetch(`${BASE_URL}/api/update-apply`, { method: "POST" })
      .then((res) => res.json())
      .then((data: { success: boolean; output: string }) => {
        if (data.success) {
          setUpdateApplyMessage("업데이트 완료! 서버가 자동으로 재시작됩니다. 잠시 후 새로고침됩니다...");
          setTimeout(() => window.location.reload(), 3000);
        } else {
          setUpdateApplyMessage(`업데이트 실패: ${data.output}`);
          setApplyingUpdate(false);
        }
      })
      .catch((err) => {
        setUpdateApplyMessage(`에러: ${err.message}`);
        setApplyingUpdate(false);
      });
  };

  if (error) return <div>에러 발생: {error}</div>;
  if (!stats)
    return (
      <div style={{ padding: "2rem 1rem" }}>
        <h1 className="aym-rise">Analyse Your Music</h1>
        <Skeleton lines={2} height={34} style={{ margin: "2rem 0 1.5rem" }} />
        <Skeleton lines={4} height={90} />
      </div>
    );

  const fmtVal = makeFmt(metric);
  const axisFmt = (v: number) => (metric === "time" ? `${Math.round(v / 60)}h` : String(v));

  // ── 구역별 문장 해설에 쓰는 값 (모두 이미 받아 둔 데이터에서 규칙으로 계산한다)
  const pkHour = peakOf(hourlyData);
  const pkDay = peakOf(weekdayData);
  const pkMonth = peakOf(monthlyData);
  const monthKo = (k: string) => `${k.slice(0, 4)}년 ${Number(k.slice(5, 7))}월`;
  const discNoun = discoveryCat === "track" ? "곡" : discoveryCat === "artist" ? "명" : "개";
  const discMonths = discoverySummary ? discoverySummary[discoveryCat].months : [];
  const discAll = discoverySummary ? discoverySummary[discoveryCat].counts : [];
  const thisMonthKey = new Date().toISOString().slice(0, 7);
  const discDone = discMonths.length && discMonths[discMonths.length - 1] === thisMonthKey ? discAll.slice(0, -1) : discAll;   // 진행 중인 달은 평균에서 뺀다
  const discRecent = discDone.slice(-6);
  const discAvg = discRecent.length >= 2 ? Math.round(discRecent.reduce((a, b) => a + b, 0) / discRecent.length) : null;
  const DIV_LABEL = { artist: "아티스트는", track: "트랙은", album: "앨범은" } as const;
  const divRows = diversity ? (["artist", "track", "album"] as const).map((k) => ({ k, score: Math.round(diversity[k].normalized_entropy * 100), top: diversity[k].top10pct_concentration })) : [];
  const divMost = divRows.length ? divRows.reduce((a, b) => (b.score > a.score ? b : a)) : null;
  const divLeast = divRows.length ? divRows.reduce((a, b) => (b.score < a.score ? b : a)) : null;
  const perDay = timeSummary && timeSummary.days > 0 ? Math.round(stats.total_scrobbles / timeSummary.days) : null;

  return (
    <ShareProvider>
    <div>
      {/* 상단 바: 로고 · 검색 · 새로고침 / 구역 이동 버튼 · 기간 */}
      <header className="aym-top">
        <div className="aym-top-row">
          <h1 className="aym-brand">
            <img src="/icon-192.png" alt="" width={32} height={32} className={refreshing ? "aym-logo spin" : "aym-logo"} />
            Analyse Your Music
            {updateInfo?.local_version && <small>v{updateInfo.local_version}</small>}
          </h1>
          <div className="aym-grow" />
          <SearchBox query={buildQuery} rangeLabel={dateRange.label} onPick={openInLibrary} />
          <button onClick={handleRefresh} disabled={refreshing} className="aym-icon-btn" title="최신 스크롭 불러오기" aria-label="최신 스크롭 불러오기">
            <span aria-hidden style={{ display: "inline-block", animation: refreshing ? "aym-spin 1s linear infinite" : undefined }}>↻</span>
          </button>
        </div>
        <div className="aym-top-row second">
          <nav className="aym-sections" aria-label="구역 이동">
            {TABS.map((t) => (
              <a key={t.id} href={`#${t.id}`} className={current === t.id ? "on" : undefined} aria-current={current === t.id ? "true" : undefined} onClick={(e) => { e.preventDefault(); goTo(t.id); }}>
                {t.label}
              </a>
            ))}
          </nav>
          <PeriodBar variant="button" range={dateRange} onChange={setDateRange} />
        </div>
      </header>

      {/* 폰에서는 구역 이동 버튼이 아래 독으로 간다 */}
      <nav className="aym-dock" aria-label="구역 이동 (하단)">
        {TABS.map((t) => (
          <a key={t.id} href={`#${t.id}`} className={current === t.id ? "on" : undefined} onClick={(e) => { e.preventDefault(); goTo(t.id); }}>
            <span className="ic" aria-hidden>{t.icon}</span>
            {t.label}
          </a>
        ))}
      </nav>

      <main className="aym-main">
      {updateInfo?.update_available && !updateDismissed && (
        <div className="aym-panel" style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap", marginTop: "1rem", borderColor: "rgba(70,157,248,0.45)", background: "rgba(70,157,248,0.1)" }}>
          <span>
            🔔 새 업데이트가 있어요
            {updateInfo.remote_version && updateInfo.local_version && updateInfo.remote_version !== updateInfo.local_version
              ? ` (v${updateInfo.local_version} → v${updateInfo.remote_version}${BUMP_LABEL[updateInfo.bump ?? ""] ? `, ${BUMP_LABEL[updateInfo.bump ?? ""]}` : ""})`
              : ""}
            {updateInfo.remote_message ? `: "${updateInfo.remote_message}"` : ""}.
            {updateApplyMessage ? ` ${updateApplyMessage}` : ""}
          </span>
          <div style={{ display: "flex", gap: "0.5rem", flexShrink: 0 }}>
            <button onClick={() => setUpdateDismissed(true)} disabled={applyingUpdate}>
              나중에 하기
            </button>
            <button onClick={handleApplyUpdate} disabled={applyingUpdate} style={{ background: "var(--track)", color: "#0b1220" }}>
              {applyingUpdate ? "업데이트 중..." : "지금 하기"}
            </button>
          </div>
        </div>
      )}

      {/* 새로고침 진행 상황 */}
      {(refreshing || refreshMessage) && (
        <div className="aym-panel" style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap", marginTop: "1rem" }}>
          <RefreshBar active={refreshing} />
          {refreshMessage && <p style={{ margin: 0, color: "var(--text-2)" }}>{refreshMessage}</p>}
        </div>
      )}

      {/* 치명적 에러는 구역과 무관하게 항상 상단에 노출 */}
      {validation && !validation.valid && (
        <div className="aym-panel" style={{ marginTop: "1rem", borderColor: "rgba(250,35,59,0.6)", background: "rgba(250,35,59,0.12)" }}>
          <strong>⚠️ 데이터에 치명적인 문제가 있습니다</strong>
          <ul style={{ margin: "0.5rem 0 0" }}>
            {validation.errors.map((e, i) => (
              <li key={i}>{e}</li>
            ))}
          </ul>
        </div>
      )}

      <PeriodBar variant="chips" range={dateRange} onChange={setDateRange} />

      {/* ───────── 01 요약 ───────── */}
      <section id="overview" className="aym-sec" style={overviewReached ? undefined : { minHeight: 700 }}>
        <Eyebrow id="overview" actions={<ShareButton spec={{ kind: "period", card: "summary", period: "all" }} label="🖼 요약 이미지 만들기" />} />
        {overviewReached && (
          <>
            <OverviewCards
              query={buildQuery}
              firstScrobble={stats.first_scrobble}
              totalScrobbles={stats.total_scrobbles}
              timeSummary={timeSummary}
              isAllTime={!dateRange.start && !dateRange.end}
            />

            <TopCards query={buildQuery} total={stats.total_scrobbles} onOpen={openInLibrary} onMore={openListInLibrary} />

            <FunFactCard />

            <div className="aym-h3">
              <h3>청취 활동 히트맵</h3>
              <span>날짜를 누르면 그날 들은 곡을 볼 수 있어요</span>
            </div>
            <MetricToggle metric={metric} onChange={setMetric} />
            <ContributionHeatmap data={dailyData} onDayClick={handleDayClick} format={fmtVal} />
          </>
        )}
      </section>

      {/* ───────── 02 청취 ───────── */}
      <section id="listening" className="aym-sec" style={listeningReached ? undefined : { minHeight: 700 }}>
        <Eyebrow id="listening" actions={<ShareButton spec={{ kind: "period", card: "clock", period: "all", metric }} />} />
        {listeningReached && (
          <>
            {pkHour && pkDay ? (
              <Lede small>
                하루 중 <b>{hourKo(parseInt(pkHour.label, 10))}</b>에 가장 많이 듣고, 요일로는 <b>{pkDay.label}요일</b>이 가장 많아요.
              </Lede>
            ) : (
              <Skeleton lines={1} height={34} style={{ marginTop: 14 }} />
            )}
            {pkHour && pkDay && (
              <Facts
                items={[
                  { label: "가장 붐비는 시간", value: hourKo(parseInt(pkHour.label, 10)), sub: fmtVal(pkHour.count) },
                  { label: "가장 바쁜 요일", value: `${pkDay.label}요일`, sub: fmtVal(pkDay.count) },
                  ...(pkMonth ? [{ label: "가장 많이 들은 달", value: monthKo(pkMonth.label), sub: fmtVal(pkMonth.count) }] : []),
                ]}
              />
            )}
            <div style={{ marginTop: 18 }}>
              <MetricToggle metric={metric} onChange={setMetric} />
            </div>

            <div className="aym-h3"><h3>청취 시계</h3></div>
            <div className="aym-panel">
              <ListeningClock data={hourlyData} format={fmtVal} noun={metric === "time" ? "청취 시간" : "스크로블"} />
            </div>

            <div className="aym-h3"><h3>월별 청취 추이</h3></div>
            <Reveal className="aym-panel" minHeight={320}>
              <ResponsiveContainer width="100%" height={280}>
                <LineChart data={monthlyData}>
                  <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} minTickGap={28} />
                  <YAxis tickFormatter={axisFmt} tick={AXIS_TICK} axisLine={false} tickLine={false} width={44} />
                  <Tooltip formatter={(v) => fmtVal(Number(v))} {...TIP} />
                  <Line type="monotone" dataKey="count" stroke="#fa233b" strokeWidth={2.5} dot={false} activeDot={{ r: 5 }} />
                </LineChart>
              </ResponsiveContainer>
            </Reveal>

            <div className="aym-h3"><h3>주간 {metric === "time" ? "청취 시간" : "스크로블"}</h3></div>
            <Reveal className="aym-panel" minHeight={300}>
              <ResponsiveContainer width="100%" height={260}>
                <AreaChart data={weekdayData}>
                  <defs>
                    <linearGradient id="weeklyGradient" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="5%" stopColor="#c490ff" stopOpacity={0.55} />
                      <stop offset="95%" stopColor="#c490ff" stopOpacity={0} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={axisFmt} tick={AXIS_TICK} axisLine={false} tickLine={false} width={44} />
                  <Tooltip formatter={(v) => fmtVal(Number(v))} {...TIP} />
                  <Area type="monotone" dataKey="count" stroke="#c490ff" strokeWidth={2.5} fill="url(#weeklyGradient)" />
                </AreaChart>
              </ResponsiveContainer>
            </Reveal>

            <div className="aym-h3"><h3>연도별 청취 추이</h3></div>
            <Reveal className="aym-panel" minHeight={300}>
              <ResponsiveContainer width="100%" height={260}>
                <BarChart data={yearlyData}>
                  <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="label" tick={AXIS_TICK} axisLine={false} tickLine={false} />
                  <YAxis tickFormatter={axisFmt} tick={AXIS_TICK} axisLine={false} tickLine={false} width={44} />
                  <Tooltip formatter={(v) => fmtVal(Number(v))} {...TIP} />
                  <Bar dataKey="count" fill="#61d4b6" radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Reveal>
          </>
        )}
      </section>

      {/* ───────── 03 음악 ───────── 연대별 · Top 10 · 순위 목록 · 상세 (정렬: 많이/오래/꾸준히/몰아/처음 들은 순) */}
      <section id="music" className="aym-sec" style={musicReached ? undefined : { minHeight: 700 }}>
        <Eyebrow id="music" />
        {musicReached && (
          <>
            <DecadeCard query={buildQuery} />
            <Library query={buildQuery} request={libraryRequest} />
          </>
        )}
      </section>

      {/* ───────── 04 발견 ───────── */}
      <section id="discovery" className="aym-sec" style={discoveryReached ? undefined : { minHeight: 600 }}>
        <Eyebrow id="discovery" />
        {discoveryReached && !discoverySummary && <Skeleton lines={4} height={60} style={{ marginTop: 20 }} />}
        {discoveryReached && discoverySummary && (
          <>
            {discAvg !== null ? (
              <Lede small>
                최근 {discRecent.length}개월 동안 매달 평균 <b className="num">{discAvg.toLocaleString()}{discNoun}</b>을 새로 만났어요.
              </Lede>
            ) : (
              <Lede small>
                지금까지 새로 만난 {discoveryCat === "track" ? "곡" : discoveryCat === "artist" ? "아티스트" : "앨범"}은 <b className="num">{discoverySummary[discoveryCat].total_new.toLocaleString()}{discNoun}</b>이에요.
              </Lede>
            )}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "0.8rem", margin: "1.3rem 0 1rem" }}>
              <CatStat title="신규 트랙" color={CAT.track.main} value={discoverySummary.track.total_new} unit="곡" />
              <CatStat title="신규 아티스트" color={CAT.artist.main} value={discoverySummary.artist.total_new} unit="명" />
              <CatStat title="신규 앨범" color={CAT.album.main} value={discoverySummary.album.total_new} unit="개" />
            </div>

            {/* 곡 / 아티스트 / 앨범 전환: 아래 월별 그래프와 최근 발견 목록이 함께 바뀐다 */}
            <div className="aym-seg" role="group" aria-label="발견 종류" style={{ margin: "0.4rem 0 0.8rem" }}>
              {(["track", "artist", "album"] as Cat[]).map((c) => (
                <button key={c} aria-pressed={discoveryCat === c} onClick={() => setDiscoveryCat(c)}>
                  {c === "track" ? "곡" : c === "artist" ? "아티스트" : "앨범"}
                </button>
              ))}
            </div>

            <div className="aym-h3">
              <h3>월별 신규 {discoveryCat === "track" ? "곡" : discoveryCat === "artist" ? "아티스트" : "앨범"} 수</h3>
            </div>
            <Reveal className="aym-panel" minHeight={300}>
              <ResponsiveContainer width="100%" height={260}>
                <LineChart
                  data={discoverySummary[discoveryCat].months.map((m, i) => ({
                    period: m,
                    count: discoverySummary[discoveryCat].counts[i],
                  }))}
                >
                  <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" vertical={false} />
                  <XAxis dataKey="period" tick={AXIS_TICK} axisLine={false} tickLine={false} minTickGap={28} />
                  <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} width={44} />
                  <Tooltip {...TIP} />
                  <Line type="monotone" dataKey="count" stroke={CAT[discoveryCat].main} strokeWidth={2.5} dot={false} activeDot={{ r: 5 }} name="신규 수" />
                </LineChart>
              </ResponsiveContainer>
            </Reveal>

            <div className="aym-h3">
              <h3>최근 발견한 {discoveryCat === "track" ? "곡" : discoveryCat === "artist" ? "아티스트" : "앨범"}</h3>
              <button onClick={() => openListInLibrary(discoveryCat, "first")}>전체 보기 (음악 · 처음 들은 순) →</button>
            </div>
            <DiscoveryList cat={discoveryCat} query={buildQuery} onOpen={openInLibrary} limit={5} />
          </>
        )}
      </section>

      {/* ───────── 05 취향 ───────── */}
      <section id="taste" className="aym-sec" style={tasteReached ? undefined : { minHeight: 700 }}>
        <Eyebrow id="taste" />
        {tasteReached && (
        <>
          {divMost && divLeast && divMost.k !== divLeast.k ? (
            <Lede small>
              {DIV_LABEL[divMost.k]} <b className="num">{divMost.score}점</b>으로 가장 고르게 듣지만, {DIV_LABEL[divLeast.k]} <b>상위 10%가 전체의 {divLeast.top}%</b>를 차지해요.
            </Lede>
          ) : (
            <Skeleton lines={1} height={34} style={{ marginTop: 14 }} />
          )}

          {diversity && (
            <>
              <div className="aym-h3"><h3>음악 소비 다양성</h3><span>100점에 가까울수록 고르게 들어요</span></div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: "0.8rem" }}>
                {(["artist", "track", "album"] as const).map((key) => {
                  const label = { artist: "아티스트", track: "트랙", album: "앨범" }[key];
                  const m = diversity[key];
                  const score = Math.round(m.normalized_entropy * 100);
                  return (
                    <div key={key} className="aym-panel">
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                        <span style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--text-2)", fontWeight: 600 }}>
                          <i style={{ width: 8, height: 8, borderRadius: "50%", background: CAT[key].main, display: "inline-block" }} />
                          {label}
                        </span>
                        <b className="num" style={{ fontSize: "1.8rem" }}>{score}</b>
                      </div>
                      <div style={{ height: 10, borderRadius: 5, background: "var(--surface-2)", margin: "0.6rem 0" }}>
                        <div style={{ width: `${score}%`, height: "100%", borderRadius: 5, background: CAT[key].main }} />
                      </div>
                      <p style={{ fontSize: "0.9rem", color: "var(--text-2)" }}>상위 10%가 전체의 {m.top10pct_concentration}% 차지</p>
                      <p style={{ color: "var(--text-3)", fontSize: "0.82rem", marginTop: 4 }}>
                        가장 많이 들은 {label}: {m.most_played.name ?? "-"} ({m.most_played.count}회)
                      </p>
                    </div>
                  );
                })}
              </div>
            </>
          )}

          {tagDistribution && <TagDistributionCard distribution={tagDistribution} query={buildQuery} baseLabel={dateRange.label} />}

          {tagEvolution && tagEvolution.periods.length > 0 && (
            <>
              <div className="aym-h3">
                <h3>취향 변화 (월별 장르 트렌드)</h3>
                <div className="aym-seg" role="group" aria-label="취향 변화 기준">
                  <button aria-pressed={evolutionMode === "fixed"} onClick={() => setEvolutionMode("fixed")}>전체 기간 기준</button>
                  <button aria-pressed={evolutionMode === "dynamic"} onClick={() => setEvolutionMode("dynamic")}>월별 실제 순위</button>
                </div>
              </div>

              <Reveal className="aym-panel" minHeight={440}>
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
                    <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="period" tick={AXIS_TICK} axisLine={false} tickLine={false} minTickGap={28} />
                    <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} width={44} />
                    <Tooltip content={<SortedTagTooltip />} />
                    {tagEvolution.series.map((s, i) => {
                      const color = TAG_COLORS[i % 8];
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
                    <CartesianGrid stroke={GRID_STROKE} strokeDasharray="3 3" vertical={false} />
                    <XAxis dataKey="period" tick={AXIS_TICK} axisLine={false} tickLine={false} minTickGap={28} />
                    <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} width={44} />
                    <Tooltip content={<SortedTagTooltip />} />
                    {tagEvolution.series.map((s, i) => (
                      <Line
                        key={s.tag}
                        type="monotone"
                        dataKey={s.tag}
                        stroke={TAG_COLORS[i % 8]}
                        connectNulls={false}
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              )}
              </Reveal>
            </>
          )}
          <div className="aym-h3">
            <h3>아티스트별 태그 {totalTagsPages && `(${artistTags.length} / ${stats.unique_artists})`}</h3>
          </div>
          <div style={{ textAlign: "left" }}>
            {artistTags.map((a, i) => (
              <RankRow
                key={a.artist}
                rank={i + 1}
                kind="artist"
                item={{ name: a.artist, artist: null, count: a.play_count }}
                max={artistTags[0]?.play_count ?? 1}
                onOpen={() => openInLibrary({ kind: "artist", name: a.artist })}
                extra={
                  <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 4 }}>
                    {a.tags.length === 0 ? (
                      <span style={{ color: "#888", fontSize: "0.8rem" }}>태그 없음</span>
                    ) : (
                      a.tags.map((t) => (
                        <span key={t} style={{ padding: "0.05rem 0.55rem", borderRadius: 999, fontSize: "0.75rem", background: CAT.artist.soft }}>
                          {t}
                        </span>
                      ))
                    )}
                  </div>
                }
              />
            ))}
          </div>

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
      </section>

      {/* ───────── 06 레이스 ───────── */}
      <section id="race" className="aym-sec" style={raceReached ? undefined : { minHeight: 500 }}>
        <Eyebrow id="race" />
        {raceReached && <RaceTab query={buildQuery} />}
      </section>

      {/* ───────── 07 데이터 ───────── 관리·설정·검증 */}
      <section id="data" className="aym-sec" style={dataReached ? undefined : { minHeight: 500 }}>
        <Eyebrow id="data" />
        {dataReached && (
          <>
            {timeSummary && perDay !== null && (
              <Lede small>
                <b className="num">{timeSummary.days.toLocaleString()}일</b> 중 <b className="num">{timeSummary.active_days.toLocaleString()}일</b> 동안 듣고, 하루 평균 <b className="num">{perDay.toLocaleString()}번</b>씩 <b className="num">{stats.total_scrobbles.toLocaleString()}번</b>의 기록이 쌓였어요.
              </Lede>
            )}
            <Facts
              items={[
                { label: "마지막 스크로블", value: stats.last_scrobble ? stats.last_scrobble.slice(0, 10).replace(/-/g, ".") : "-" },
                ...(tagDistribution ? [{ label: "장르 태그 반영", value: `${tagDistribution.total_artists ? Math.round((tagDistribution.covered_artists / tagDistribution.total_artists) * 100) : 0}%`, sub: `${tagDistribution.covered_artists.toLocaleString()} / ${tagDistribution.total_artists.toLocaleString()}명` }] : []),
                ...(timeSummary ? [{ label: "길이를 아는 재생", value: `${Math.round(timeSummary.coverage * 100)}%` }] : []),
                ...(validation ? [{ label: "데이터 검사", value: validation.valid ? (validation.warnings.length ? `경고 ${validation.warnings.length}건` : "이상 없음") : "문제 있음" }] : []),
              ]}
            />
        <div style={{ maxWidth: 860, textAlign: "left", display: "grid", gap: "1.2rem", marginTop: "1.6rem" }}>
          {/* AI 분석용 프롬프트 */}
          <section style={DATA_PANEL}>
            <h2 style={DATA_TITLE}>AI 분석용 프롬프트 생성</h2>
            <p style={{ color: "#999", fontSize: "0.9rem", margin: "0 0 1rem" }}>
              위쪽에서 고른 기간(<strong style={{ color: "CanvasText" }}>{dateRange.label}</strong>)의 청취 데이터를 정리한 프롬프트를 만들어요. 복사해서 ChatGPT나 Claude 같은 AI에게 붙여넣고 취향 분석을 물어보면 됩니다.
            </p>
            {promptPeriod && (
              <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", margin: "0 0 1rem", cursor: "pointer", fontSize: "0.9rem" }}>
                <input type="checkbox" checked={compareWithPrev} onChange={(e) => setCompareWithPrev(e.target.checked)} />
                {{ year: "전년과 비교", month: "직전 달과 비교", week: "직전 주와 비교" }[promptPeriod.kind]}하는 프롬프트로 만들기
              </label>
            )}
            <button
              onClick={handleGeneratePrompt}
              disabled={generatingPrompt}
              style={{ padding: "0.5rem 1rem" }}
            >
              {generatingPrompt ? "생성 중..." : "📋 프롬프트 생성"}
            </button>
            {promptNote && <p style={{ color: "#999", fontSize: "0.85rem", margin: "0.75rem 0 0" }}>{promptNote}</p>}

            {aiPrompt && (
              <div style={{ marginTop: "1rem" }}>
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
          </section>

          {/* 설정 */}
          <section style={DATA_PANEL}>
            <h2 style={DATA_TITLE}>⚙️ 설정</h2>
            <div style={{ maxWidth: 440 }}>
              <label style={DATA_LABEL}>Last.fm API Key {configStatus?.has_api_key && "(설정됨 — 바꿀 때만 입력)"}</label>
              <input
                type="password"
                value={apiKeyInput}
                onChange={(e) => setApiKeyInput(e.target.value)}
                placeholder={configStatus?.has_api_key ? "••••••••" : "last.fm/api/account/create 에서 발급"}
                style={DATA_INPUT}
              />

              <label style={DATA_LABEL}>Last.fm 유저네임</label>
              <input
                type="text"
                value={usernameInput}
                onChange={(e) => setUsernameInput(e.target.value)}
                placeholder="last.fm 프로필의 아이디"
                style={DATA_INPUT}
              />

              <label style={DATA_LABEL}>Apple Music 내보내기 폴더 (선택)</label>
              <input
                type="text"
                value={appleDirInput}
                onChange={(e) => setAppleDirInput(e.target.value)}
                placeholder="예: /Users/me/Downloads/Apple Music Activity"
                style={{ ...DATA_INPUT, marginBottom: "0.4rem" }}
              />
              <div style={{ color: "#999", fontSize: "0.8rem", marginBottom: "0.9rem", lineHeight: 1.6 }}>
                privacy.apple.com 에서 받은 “Apple Music 활동” 폴더 경로예요. 비워 두면 Last.fm 데이터만 쓰고, 지정하면 가짜/중복 스크로블 판정·곡 길이·빈 아티스트 채우기가 Apple 기록을 근거로 써요.
                압축을 푼 맨 위 폴더를 적어도 안에서 찾아요.
              </div>

              <button onClick={handleSaveConfig} disabled={savingConfig} style={{ padding: "0.5rem 1rem" }}>
                {savingConfig ? "저장 중..." : "저장"}
              </button>
              {configMessage && <p style={{ color: "#999", margin: "0.6rem 0 0" }}>{configMessage}</p>}
            </div>

            <div style={{ marginTop: "1.2rem" }}>
              <AppleFiles appleDir={configStatus?.apple_dir ?? ""} />
            </div>

            <div style={{ marginTop: "1.2rem", paddingTop: "1.2rem", borderTop: "1px solid rgba(128,128,128,0.25)" }}>
              <button onClick={handleInstallDeps} disabled={installingDeps} style={{ padding: "0.5rem 1rem" }}>
                {installingDeps ? "설치 중..." : "📦 의존 모듈 설치"}
              </button>
              {installMessage && <p style={{ color: "#999", margin: "0.6rem 0 0" }}>{installMessage}</p>}
            </div>
          </section>

          {/* 데이터 상태 */}
          <section style={DATA_PANEL}>
            <h2 style={DATA_TITLE}>데이터 상태</h2>

            {validation && (
              <>
                <p style={{ margin: "0 0 0.8rem" }}>총 데이터 행 수: <strong>{validation.total_rows.toLocaleString()}</strong></p>

                {validation.valid && validation.warnings.length > 0 && (
                  <div
                    style={{
                      background: "rgba(255,184,107,0.12)",
                      color: "var(--text)",
                      border: "1px solid rgba(255,184,107,0.5)",
                      borderRadius: 14,
                      padding: "0.9rem 1rem",
                      marginBottom: "1rem",
                    }}
                  >
                    <strong>⚠️ 데이터 검증 경고 ({validation.warnings.length}건)</strong>
                    <ul style={{ margin: "0.5rem 0 0", paddingLeft: "1.2rem" }}>
                      {validation.warnings.map((w, i) => (
                        <li key={i}>{w}</li>
                      ))}
                    </ul>
                  </div>
                )}

                {validation.valid && validation.warnings.length === 0 && (
                  <p style={{ color: "var(--album)", margin: "0 0 1rem" }}>✅ 검증 통과, 문제 없음</p>
                )}
              </>
            )}

            <div style={{ marginBottom: "1rem" }}>
              <div style={{ color: "#999", fontSize: "0.85rem", marginBottom: "0.4rem" }}>
                아티스트 태그(장르) 캐시{tagDistribution ? `: ${tagDistribution.covered_artists.toLocaleString()} / ${tagDistribution.total_artists.toLocaleString()}명` : ""} — 새로고침 때 새 아티스트는 자동으로 채워집니다.
              </div>
              <button onClick={handleFetchTagCache} disabled={cachingTags} style={{ padding: "0.5rem 1rem" }}>
                {cachingTags ? "태그 조회 중..." : "🏷️ 아티스트 태그 20명 더 불러오기"}
              </button>
              {cacheMessage && <p style={{ margin: "0.6rem 0 0", color: "#999" }}>{cacheMessage}</p>}
            </div>

            <button onClick={handleInvalidateAliasCache} disabled={invalidating} style={{ padding: "0.5rem 1rem" }}>
              {invalidating ? "처리 중..." : "🔄 매핑된 아티스트 캐시 초기화"}
            </button>
            {invalidateMessage && <p style={{ margin: "0.6rem 0 0", color: "#999" }}>{invalidateMessage}</p>}
          </section>
        </div>
          </>
        )}
      </section>
      </main>

      {selectedDay && (
        <DayDetailModal
          detail={dayDetail}
          loading={loadingDayDetail}
          onClose={() => setSelectedDay(null)}
        />
      )}
    </div>
    </ShareProvider>
  );
}

export default App;