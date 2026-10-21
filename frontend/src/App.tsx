import { useEffect, useState, useCallback, useRef, type CSSProperties } from "react";
import { BASE_URL } from "./config";
import { Library, type LibraryRequest, type LibraryTarget, type SortMode } from "./Library";
import { ShareButton, ShareProvider } from "./Share";
import { CatStat, OverviewCards } from "./OverviewCards";
import { DiscoveryList } from "./DiscoveryList";
import { CAT, type Cat } from "./theme";
import { ALL_TIME, PeriodBar } from "./PeriodBar";
import { Skeleton } from "./motion";
import { RankRow } from "./RankRow";
import { SearchBox } from "./Search";
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

type TabId = "overview" | "listening" | "music" | "discovery" | "taste" | "data";

const TABS: { id: TabId; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "listening", label: "Listening" },
  { id: "music", label: "Music" },
  { id: "discovery", label: "Discovery" },
  { id: "taste", label: "Taste" },
  { id: "data", label: "Data" },
];

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
const DATA_PANEL: CSSProperties = { border: "1px solid rgba(128,128,128,0.3)", borderRadius: 10, padding: "1.2rem 1.3rem" };
const DATA_TITLE: CSSProperties = { margin: "0 0 0.8rem", fontSize: "1.2rem" };
const DATA_LABEL: CSSProperties = { display: "block", fontSize: "0.85rem", color: "#999", margin: "0 0 0.3rem" };
const DATA_INPUT: CSSProperties = { width: "100%", padding: "0.5rem", marginBottom: "0.9rem", boxSizing: "border-box" };

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
    if (count === 0) return "rgba(128,128,128,0.22)";
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
        <svg viewBox={`0 0 ${width} ${height}`} style={{ width: "100%", minWidth: 640, height: "auto", display: "block" }}>
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
    <div ref={containerRef} style={{ position: "relative", display: "flex", alignItems: "center", justifyContent: "center", gap: "2.5rem", flexWrap: "wrap" }}>
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
            <path d={describeWedge(rOuterMax, startAngle, endAngle)} fill={isHovered ? "rgba(128,128,128,0.4)" : "rgba(128,128,128,0.22)"} />
            {d.count > 0 && (
              <path
                d={describeWedge(rOuter, startAngle, endAngle)}
                fill={interpolateColor("#bfdbfe", "#2563eb", ratio)}
                stroke={isHovered ? "#111" : "none"}
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
          background: "Canvas",
          color: "CanvasText",
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
    setActiveTab("music");
  };
  const openListInLibrary = (category: Cat, sort: SortMode) => {
    setLibraryRequest({ id: Date.now(), list: { category, sort } });
    setActiveTab("music");
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

  const [activeTab, setActiveTab] = useState<TabId>("overview");

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
  }, [buildQuery, evolutionMode]);

  useEffect(() => {
    loadAllData();
  }, [loadAllData]);

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

  // 날짜 범위가 바뀔 때마다 1쪽부터 다시 불러온다 (이전 목록은 새 응답이 올 때까지 그대로 둔다)
  useEffect(() => {
    loadArtistTagsPage(1);
  }, [loadArtistTagsPage]);

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

  return (
    <ShareProvider>
    <div style={{ padding: "2rem", fontFamily: "sans-serif" }}>
      <h1>Analyse Your Music</h1>

      {updateInfo?.update_available && !updateDismissed && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: "1rem",
            background: "#eef6ff",
            border: "1px solid #8ec0f2",
            borderRadius: 8,
            padding: "0.75rem 1rem",
            marginBottom: "1rem",
          }}
        >
          <span>
            🔔 새 업데이트가 있어요{updateInfo.remote_message ? `: "${updateInfo.remote_message}"` : ""}.
            {updateApplyMessage ? ` ${updateApplyMessage}` : ""}
          </span>
          <div style={{ display: "flex", gap: "0.5rem", flexShrink: 0 }}>
            <button
              onClick={() => setUpdateDismissed(true)}
              disabled={applyingUpdate}
              style={{ padding: "0.3rem 0.6rem" }}
            >
              나중에 하기
            </button>
            <button
              onClick={handleApplyUpdate}
              disabled={applyingUpdate}
              style={{ padding: "0.3rem 0.6rem", background: "#2563eb", color: "white" }}
            >
              {applyingUpdate ? "업데이트 중..." : "지금 하기"}
            </button>
          </div>
        </div>
      )}

      {/* 상단 컨트롤: 새로고침 (기간 선택은 탭 아래 PeriodBar 로 통합) */}
      <div style={{ marginBottom: "1rem", display: "flex", gap: "1rem", alignItems: "center", flexWrap: "wrap" }}>
        <button onClick={handleRefresh} disabled={refreshing} style={{ padding: "0.5rem 1rem" }}>
          {refreshing ? "업데이트 중..." : "🔄 최신 스크롭 불러오기"}
        </button>
        <SearchBox query={buildQuery} rangeLabel={dateRange.label} onPick={openInLibrary} />
      </div>

      {/* 탭 바 */}
      <div className="tab-bar" style={{ display: "flex", gap: "0.5rem", borderBottom: "1px solid #ddd", marginBottom: "1.5rem", overflowX: "auto" }}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              flexShrink: 0,
              whiteSpace: "nowrap",
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

      <PeriodBar range={dateRange} onChange={setDateRange} />

      {refreshMessage && <p>{refreshMessage}</p>}

      {/* 치명적 에러는 탭과 무관하게 항상 상단에 노출 */}
      {validation && !validation.valid && (
        <div
          style={{
            background: "#fdd",
            color: "#222",
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

      <div key={activeTab} className="aym-tab">
      {/* Overview 탭 */}
      {activeTab === "overview" && (
        <>
          <div style={{ display: "flex", justifyContent: "flex-end", margin: "0.4rem 0" }}>
            <ShareButton spec={{ kind: "period", card: "summary", period: "all" }} label="🖼 요약 이미지 만들기" />
          </div>
          <OverviewCards
            query={buildQuery}
            firstScrobble={stats.first_scrobble}
            totalScrobbles={stats.total_scrobbles}
            timeSummary={timeSummary}
            isAllTime={!dateRange.start && !dateRange.end}
          />

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
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
          <h2>청취 시계</h2>
          <ShareButton spec={{ kind: "period", card: "clock", period: "all", metric }} />
        </div>
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
      {/* Music 탭: Top 10 · 순위 목록 · 상세 (정렬: 많이/오래/꾸준히/몰아/처음 들은 순) */}
      {activeTab === "music" && <Library query={buildQuery} request={libraryRequest} />}

      {/* Discovery 탭 */}
      {activeTab === "discovery" && discoverySummary && (
        <>
          <h2 style={{ textAlign: "left" }}>새로 발견한 음악</h2>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "0.8rem", margin: "0.6rem 0 1rem" }}>
            <CatStat title="신규 트랙" color={CAT.track.main} value={discoverySummary.track.total_new} unit="곡" />
            <CatStat title="신규 아티스트" color={CAT.artist.main} value={discoverySummary.artist.total_new} unit="명" />
            <CatStat title="신규 앨범" color={CAT.album.main} value={discoverySummary.album.total_new} unit="개" />
          </div>

          {/* 곡 / 아티스트 / 앨범 전환: 아래 월별 그래프와 최근 발견 목록이 함께 바뀐다 */}
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", margin: "0.4rem 0 0.8rem" }}>
            {(["track", "artist", "album"] as Cat[]).map((c) => (
              <button
                key={c}
                onClick={() => setDiscoveryCat(c)}
                style={{
                  padding: "0.35rem 0.9rem",
                  fontWeight: discoveryCat === c ? 700 : 400,
                  borderStyle: "solid",
                  borderWidth: discoveryCat === c ? "2px 2px 3px 2px" : "1px 1px 3px 1px",
                  borderColor: discoveryCat === c ? CAT[c].main : `#666 #666 ${CAT[c].main} #666`,
                  color: discoveryCat === c ? CAT[c].main : undefined,
                }}
              >
                {c === "track" ? "곡" : c === "artist" ? "아티스트" : "앨범"}
              </button>
            ))}
          </div>

          <h3 style={{ textAlign: "left", borderLeft: `4px solid ${CAT[discoveryCat].main}`, paddingLeft: "0.6rem" }}>
            월별 신규 {discoveryCat === "track" ? "곡" : discoveryCat === "artist" ? "아티스트" : "앨범"} 수
          </h3>
          <ResponsiveContainer width="100%" height={260}>
            <LineChart
              data={discoverySummary[discoveryCat].months.map((m, i) => ({
                period: m,
                count: discoverySummary[discoveryCat].counts[i],
              }))}
            >
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="period" tick={{ fontSize: 11 }} angle={-45} textAnchor="end" height={60} />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="count" stroke={CAT[discoveryCat].main} strokeWidth={2} name="신규 수" />
            </LineChart>
          </ResponsiveContainer>

          <h3 style={{ textAlign: "left", borderLeft: `4px solid ${CAT[discoveryCat].main}`, paddingLeft: "0.6rem" }}>
            최근 발견한 {discoveryCat === "track" ? "곡" : discoveryCat === "artist" ? "아티스트" : "앨범"}
          </h3>
          <DiscoveryList cat={discoveryCat} query={buildQuery} onOpen={openInLibrary} limit={5} />
          <div style={{ textAlign: "right", marginTop: "0.5rem" }}>
            <button onClick={() => openListInLibrary(discoveryCat, "first")} style={{ background: "none", border: "none", color: "#6a9bd8", cursor: "pointer", font: "inherit" }}>
              전체 보기 (Music 탭 · 처음 들은 순) →
            </button>
          </div>
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
                  (재생 {tagDistribution.total_plays ? Math.round((tagDistribution.covered_plays / tagDistribution.total_plays) * 100) : 0}% 반영 ·
                  아티스트 {tagDistribution.covered_artists} / {tagDistribution.total_artists}명)
                </span>
              </h2>
              <ResponsiveContainer width="100%" height={Math.max(300, tagDistribution.tags.length * 34 + 40)}>
                <BarChart data={tagDistribution.tags} layout="vertical">
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis type="number" />
                  <YAxis dataKey="tag" type="category" width={150} interval={0} tick={{ fontSize: 13 }} />
                  <Tooltip />
                  <Bar dataKey="score" fill="#ff7f50" />
                </BarChart>
              </ResponsiveContainer>
            </>
          )}

          {tagEvolution && tagEvolution.periods.length > 0 && (
            <>
              <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap", margin: "3rem 0 1rem" }}>
                <h2 style={{ margin: 0 }}>취향 변화 (월별 장르 트렌드)</h2>
                <div>
                  <button
                    onClick={() => setEvolutionMode("fixed")}
                    style={{
                      padding: "0.3rem 0.8rem",
                      marginLeft: "0.4rem",
                      fontWeight: evolutionMode === "fixed" ? 700 : 400,
                      border: evolutionMode === "fixed" ? "2px solid #8884d8" : "1px solid #666",
                    }}
                  >
                    전체 기간 기준
                  </button>
                  <button
                    onClick={() => setEvolutionMode("dynamic")}
                    style={{
                      padding: "0.3rem 0.8rem",
                      marginLeft: "0.4rem",
                      fontWeight: evolutionMode === "dynamic" ? 700 : 400,
                      border: evolutionMode === "dynamic" ? "2px solid #8884d8" : "1px solid #666",
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
          <h2 style={{ textAlign: "left", borderLeft: `4px solid ${CAT.artist.main}`, paddingLeft: "0.6rem" }}>
            아티스트별 태그 {totalTagsPages && `(${artistTags.length} / ${stats.unique_artists})`}
          </h2>
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

      {/* Data 탭 */}
      {activeTab === "data" && (
        <div style={{ maxWidth: 760, margin: "0 auto", textAlign: "left", display: "grid", gap: "1.5rem" }}>
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
                {configStatus?.apple_dir ? (
                  <div>
                    {([["play_activity", "재생 로그"], ["daily_tracks", "일별 곡 목록"], ["library_xml", "보관함 XML"]] as const).map(([k, name]) => (
                      <span key={k} style={{ marginRight: "0.8rem" }}>
                        {configStatus.apple_files?.[k] ? "✅" : "▫️"} {name}
                      </span>
                    ))}
                  </div>
                ) : null}
              </div>

              <button onClick={handleSaveConfig} disabled={savingConfig} style={{ padding: "0.5rem 1rem" }}>
                {savingConfig ? "저장 중..." : "저장"}
              </button>
              {configMessage && <p style={{ color: "#999", margin: "0.6rem 0 0" }}>{configMessage}</p>}
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
                      background: "#fff3cd",
                      color: "#222",
                      border: "1px solid #e0a800",
                      borderRadius: 8,
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
                  <p style={{ color: "#2a2", margin: "0 0 1rem" }}>✅ 검증 통과, 문제 없음</p>
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
      )}
      </div>

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