import { useEffect, useState, useCallback } from "react";
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

type DailyPoint = { date: string; count: number };

type DiscoverySummary = {
  track: { total_new: number; months: string[]; counts: number[] };
  artist: { total_new: number; months: string[]; counts: number[] };
  album: { total_new: number; months: string[]; counts: number[] };
};

type DiscoveryItem = {
  name: string;
  artist: string | null;
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

type TopItem = {
  name: string;
  count: number;
  artist: string | null;
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

const BASE_URL = "http://localhost:8000";

function ContributionHeatmap({ data }: { data: DailyPoint[] }) {
  const countMap = new Map(data.map((d) => [d.date, d.count]));

  if (data.length === 0) return null;

  // 데이터 범위의 시작일을 그 주의 일요일로 맞춤
  const dates = data.map((d) => new Date(d.date)).sort((a, b) => a.getTime() - b.getTime());
  const firstDate = new Date(dates[0]);
  const lastDate = new Date(dates[dates.length - 1]);

  const startDate = new Date(firstDate);
  startDate.setDate(startDate.getDate() - startDate.getDay());

  const maxCount = Math.max(...data.map((d) => d.count), 1);

  const getColor = (count: number) => {
    if (count === 0) return "#ebedf0";
    const ratio = count / maxCount;
    if (ratio < 0.25) return "#9be9a8";
    if (ratio < 0.5) return "#40c463";
    if (ratio < 0.75) return "#30a14e";
    return "#216e39";
  };

  const weeks: { date: string; count: number }[][] = [];
  let cursor = new Date(startDate);

  while (cursor <= lastDate) {
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
    if (d.getMonth() !== lastMonth) {
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
    <div style={{ overflowX: "auto" }}>
      <svg width={width} height={height}>
        {monthLabels.map((m, i) => (
          <text key={i} x={m.x} y={10} fontSize={10} fill="#888">
            {m.label}
          </text>
        ))}
        {weeks.map((week, wi) =>
          week.map((day, di) => (
            <rect
              key={`${wi}-${di}`}
              x={wi * (cellSize + cellGap)}
              y={di * (cellSize + cellGap) + 20}
              width={cellSize}
              height={cellSize}
              rx={2}
              fill={getColor(day.count)}
            >
              <title>
                {day.date}: {day.count}회
              </title>
            </rect>
          ))
        )}
      </svg>
    </div>
  );
}

function App() {
  const [dailyData, setDailyData] = useState<DailyPoint[]>([]);

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

  const [tagDistribution, setTagDistribution] = useState<TagDistribution | null>(null);
  const [tagEvolution, setTagEvolution] = useState<TagEvolution | null>(null);
  const [evolutionMode, setEvolutionMode] = useState<"fixed" | "dynamic">("fixed");

  const [diversity, setDiversity] = useState<Diversity | null>(null);

  const [artistTags, setArtistTags] = useState<ArtistTagResult[]>([]);
  const [tagsPage, setTagsPage] = useState(1);
  const [totalTagsPages, setTotalTagsPages] = useState<number | null>(null);
  const [loadingTags, setLoadingTags] = useState(false);

  const [refreshing, setRefreshing] = useState(false);
  const [refreshMessage, setRefreshMessage] = useState<string | null>(null);

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

  const loadAllData = useCallback(() => {
    const qs = buildQuery();

    fetch(`${BASE_URL}/api/listening/daily${qs}`)
      .then((res) => res.json())
      .then((data) => setDailyData(data.days))
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/stats${qs}`)
      .then((res) => res.json())
      .then(setStats)
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/listening/hourly${qs}`)
      .then((res) => res.json())
      .then((data) => {
        const points = data.hours.map((h: number, i: number) => ({
          label: `${h}시`,
          count: data.counts[i],
        }));
        setHourlyData(points);
      })
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/listening/weekday${qs}`)
      .then((res) => res.json())
      .then((data) => {
        const points = data.weekdays.map((w: string, i: number) => ({
          label: w,
          count: data.counts[i],
        }));
        setWeekdayData(points);
      })
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/listening/monthly${qs}`)
      .then((res) => res.json())
      .then((data) => {
        const points = data.months.map((m: string, i: number) => ({
          label: m,
          count: data.counts[i],
        }));
        setMonthlyData(points);
      })
      .catch((err) => setError(err.message));

    fetch(`${BASE_URL}/api/listening/yearly${qs}`)
      .then((res) => res.json())
      .then((data) => {
        const points = data.years.map((y: number, i: number) => ({
          label: String(y),
          count: data.counts[i],
        }));
        setYearlyData(points);
      })
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
      .then((data) => setTopAlbums(data.results))
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
          setRefreshMessage("업데이트 완료! 잠시 후 새로고침됩니다...");
          setTimeout(() => {
            window.location.reload();
          }, 1000);
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

  if (error) return <div>에러 발생: {error}</div>;
  if (!stats) return <div>불러오는 중...</div>;

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
      </div>

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
          <ContributionHeatmap data={dailyData} />
        </>
      )}

      {/* Listening 탭 */}
      {activeTab === "listening" && (
        <>
          <h2>시간대별 청취 패턴</h2>
          <ResponsiveContainer width="100%" height={350}>
            <BarChart data={hourlyData} margin={{ bottom: 40 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="label"
                interval={0}
                angle={-45}
                textAnchor="end"
                tick={{ fontSize: 13 }}
                height={60}
              />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#8884d8" />
            </BarChart>
          </ResponsiveContainer>

          <h2>요일별 청취 패턴</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={weekdayData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#82ca9d" />
            </BarChart>
          </ResponsiveContainer>

          <h2>월별 청취 추이</h2>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={monthlyData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" />
              <YAxis />
              <Tooltip />
              <Line type="monotone" dataKey="count" stroke="#8884d8" />
            </LineChart>
          </ResponsiveContainer>

          <h2>연도별 청취 추이</h2>
          <ResponsiveContainer width="100%" height={300}>
            <BarChart data={yearlyData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis dataKey="label" />
              <YAxis />
              <Tooltip />
              <Bar dataKey="count" fill="#82ca9d" />
            </BarChart>
          </ResponsiveContainer>
        </>
      )}

      {/* Music 탭 */}
      {activeTab === "music" && (
        <>
          <h2>Top 10</h2>
          <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 250 }}>
              <h3>Artists</h3>
              <ol>
                {topArtists.map((item, i) => (
                  <li key={i}>
                    {item.name} <span style={{ color: "#888" }}>({item.count}회)</span>
                  </li>
                ))}
              </ol>
            </div>

            <div style={{ flex: 1, minWidth: 250 }}>
              <h3>Tracks</h3>
              <ol>
                {topTracks.map((item, i) => (
                  <li key={i}>
                    {item.name}
                    {item.artist && <span style={{ color: "#888" }}> - {item.artist}</span>}{" "}
                    <span style={{ color: "#888" }}>({item.count}회)</span>
                  </li>
                ))}
              </ol>
            </div>

            <div style={{ flex: 1, minWidth: 250 }}>
              <h3>Albums</h3>
              <ol>
                {topAlbums.map((item, i) => (
                  <li key={i}>
                    {item.name}
                    {item.artist && <span style={{ color: "#888" }}> - {item.artist}</span>}{" "}
                    <span style={{ color: "#888" }}>({item.count}회)</span>
                  </li>
                ))}
              </ol>
            </div>
          </div>
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
          <ol>
            {discoveryTimeline.map((item, i) => (
              <li key={i}>
                {item.name}
                {item.artist && <span style={{ color: "#888" }}> - {item.artist}</span>}{" "}
                <span style={{ color: "#888" }}>({item.first_listened})</span>
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
                  <Tooltip />
                  {tagEvolution.series.map((s, i) => (
                    <Line
                      key={s.tag}
                      type="monotone"
                      dataKey={s.tag}
                      stroke={
                        ["#8884d8", "#82ca9d", "#ff7f50", "#ffc658", "#a4de6c", "#d0ed57", "#d62728", "#9467bd"][
                          i % 8
                        ]
                      }
                      connectNulls={false}
                    />
                  ))}
                </LineChart>
              </ResponsiveContainer>
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
    </div>
  );
}

export default App;