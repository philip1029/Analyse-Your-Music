import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { BASE_URL } from "./config";
import { dominantColor } from "./coverColor";
import { fmtHM, longDate } from "./format";
import { Num, stagger, useCountUp } from "./motion";
import { ShareButton, cover } from "./Share";
import { CAT } from "./theme";

// 연말 리플레이 스토리: 한 해의 기록을 전체 화면 슬라이드로 넘겨 본다 (인스타그램 스토리·Apple Music 리플레이식).
// 탭/클릭으로 앞뒤 이동, 자동으로 넘어가고, 누르고 있으면 멈춘다. 문장·수치는 모두 받아 온 기록에서 규칙으로 계산한다 (AI 없음).

const SLIDE_MS = 6500;

type Top = { name: string; artist: string | null; album?: string | null; count: number };
type TimeSummary = { total_seconds: number; coverage: number; days: number; active_days: number; avg_seconds_per_day: number; busiest_day: { date: string; seconds: number; plays: number } | null };
type Stats = { total_scrobbles: number; unique_tracks: number; unique_artists: number; unique_albums: number; first_scrobble: string | null; last_scrobble: string | null };
type Data = {
  time: TimeSummary | null;
  stats: Stats | null;
  top: Record<"artist" | "album" | "track", Top[]>;
  months: { months: string[]; counts: number[] } | null;
  hours: number[] | null;
  tags: { tag: string; score: number }[];
  newCounts: { artist: number; album: number; track: number } | null;   // 그 해에 "처음" 들은 수 (전체 기간 기준)
  isFirstYear: boolean;
};
type Slide = { key: string; tint: string; node: ReactNode };

const pct = (n: number, total: number) => (total > 0 ? Math.round((n / total) * 1000) / 10 : 0);
const hourKo = (h: number) => (h === 0 ? "자정" : h === 12 ? "정오" : `${h < 12 ? "오전" : "오후"} ${h % 12}시`);

const q = (year: number) => `start=${year}-01-01&end=${year}-12-31`;
const getJson = <T,>(path: string): Promise<T | null> =>
  fetch(`${BASE_URL}${path}`)
    .then((r) => r.json())
    .then((d) => (d && !d.error ? (d as T) : null))
    .catch(() => null);

async function loadYear(year: number): Promise<Data> {
  const r = q(year);
  const top = (c: string) => getJson<{ results: Top[] }>(`/api/music/top?category=${c}&limit=5&metric=plays&${r}`).then((d) => d?.results ?? []);
  const [time, stats, artist, album, track, months, hours, tags, disc] = await Promise.all([
    getJson<TimeSummary>(`/api/time/summary?${r}`),
    getJson<Stats>(`/api/stats?${r}`),
    top("artist"),
    top("album"),
    top("track"),
    getJson<{ months: string[]; counts: number[] }>(`/api/listening/monthly?${r}`),
    getJson<{ counts: number[] }>(`/api/listening/hourly?${r}`),
    getJson<{ tags: { tag: string; score: number }[] }>(`/api/taste/tag-distribution?${r}`),
    // 범위를 주면 "그 해에 들은 전부"가 나오므로, "처음 들은 수"는 전체 기간 월별 신규 수를 연도별로 합친다
    getJson<Record<"artist" | "album" | "track", { months: string[]; counts: number[] }>>(`/api/discovery/summary`),
  ]);
  let newCounts: Data["newCounts"] = null;
  let isFirstYear = false;
  if (disc) {
    const sum = (k: "artist" | "album" | "track") => disc[k].months.reduce((a, m, i) => a + (m.startsWith(String(year)) ? disc[k].counts[i] : 0), 0);
    newCounts = { artist: sum("artist"), album: sum("album"), track: sum("track") };
    isFirstYear = disc.track.months.length > 0 && disc.track.months[0].startsWith(String(year));
  }
  return { time, stats, top: { artist, album, track }, months, hours: hours?.counts ?? null, tags: tags?.tags ?? [], newCounts, isFirstYear };
}

// ── 슬라이드 공용 조각 ──────────────────────────────────────────────

const label: CSSProperties = { fontSize: "3.6cqw", fontWeight: 800, letterSpacing: "0.12em", textTransform: "uppercase", color: "rgba(255,255,255,0.7)" };
const huge: CSSProperties = { fontSize: "17cqw", fontWeight: 900, letterSpacing: "-0.05em", lineHeight: 0.95 };
const lede: CSSProperties = { fontSize: "7.2cqw", fontWeight: 800, letterSpacing: "-0.04em", lineHeight: 1.2 };
const sub: CSSProperties = { fontSize: "4cqw", color: "rgba(255,255,255,0.72)", lineHeight: 1.45 };

// 큰 숫자 + 단위("1,180시간 14분", "534명"): 숫자는 크게, 한글 단위는 작게 떼어서 겹치지 않게 한다. 폭은 최종 값으로 고정해 굴러가도 줄이 흔들리지 않는다.
function NumUnits({ value, format, duration }: { value: number; format: (n: number) => string; duration?: number }) {
  const shown = useCountUp(value, duration);
  const render = (t: string) =>
    t.split(/(\d[\d,.]*)/).map((part, i) =>
      /^\d/.test(part) ? <span key={i}>{part}</span> : part ? <span key={i} style={{ fontSize: "0.48em", marginLeft: "0.1em", marginRight: "0.04em", letterSpacing: 0, fontWeight: 800 }}>{part}</span> : null
    );
  return (
    <span style={{ display: "inline-grid", fontVariantNumeric: "tabular-nums" }}>
      <span aria-hidden style={{ gridArea: "1 / 1", visibility: "hidden" }}>{render(format(value))}</span>
      <span style={{ gridArea: "1 / 1", textAlign: "right" }}>{render(format(shown))}</span>
    </span>
  );
}

function Rise({ i, children, style }: { i: number; children: ReactNode; style?: CSSProperties }) {
  return (
    <div className="aym-rise" style={{ ...stagger(i, 130, 900), ...style }}>
      {children}
    </div>
  );
}

function Bars({ values, hi, color, labels }: { values: number[]; hi: number; color: string; labels: [string, string, string?] }) {
  const max = Math.max(...values, 1);
  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: "1cqw", height: "30cqw" }}>
        {values.map((v, i) => (
          <i
            key={i}
            className="aym-spark"
            style={{ flex: 1, height: `${Math.max(3, (v / max) * 100)}%`, borderRadius: "1.2cqw 1.2cqw 0.5cqw 0.5cqw", background: i === hi ? color : "rgba(255,255,255,0.28)", animationDelay: `${300 + i * 45}ms` }}
          />
        ))}
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: "3cqw", color: "rgba(255,255,255,0.55)", marginTop: "1.5cqw" }}>
        <span>{labels[0]}</span>
        {labels[2] && <span>{labels[2]}</span>}
        <span>{labels[1]}</span>
      </div>
    </div>
  );
}

// 카드 폭에 맞춰 정사각형으로 늘고 주는 커버 (Cover 컴포넌트는 크기가 px 고정이라 폰에서 찌그러진다)
function StoryCover({ kind, artist, album }: { kind: "artist" | "album"; artist: string | null; album?: string | null }) {
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setSrc(null);
    (kind === "artist" ? cover("artist", artist) : cover("album", artist, album)).then((img) => !cancelled && setSrc(img?.src ?? null));
    return () => {
      cancelled = true;
    };
  }, [kind, artist, album]);
  const letter = Array.from((kind === "artist" ? artist : album) ?? "♪")[0];
  return (
    <div style={{ width: "52cqw", height: "52cqw", borderRadius: kind === "artist" ? "50%" : "3cqw", overflow: "hidden", boxShadow: "0 3cqw 8cqw rgba(0,0,0,0.5)", background: "rgba(255,255,255,0.12)", display: "grid", placeItems: "center", fontSize: "18cqw", fontWeight: 800, color: "rgba(255,255,255,0.5)" }}>
      {src ? <img src={src} alt="" style={{ width: "100%", height: "100%", objectFit: "cover", display: "block" }} /> : letter}
    </div>
  );
}

// 1위 + 2~5위 목록 (커버가 있는 TOP 슬라이드)
function TopSlide({ kind, items, total, year }: { kind: "artist" | "album" | "track"; items: Top[]; total: number; year: number }) {
  const first = items[0];
  const title = { artist: "올해의 아티스트", album: "올해의 앨범", track: "올해의 트랙" }[kind];
  const big = kind === "artist" ? <StoryCover kind="artist" artist={first.name} /> : <StoryCover kind="album" artist={first.artist} album={kind === "album" ? first.name : first.album} />;
  return (
    <>
      <Rise i={0}><div style={label}>{year} · {title}</div></Rise>
      <Rise i={1} style={{ marginTop: "5cqw" }}>
        <div className="aym-story-cover">{big}</div>
      </Rise>
      <Rise i={2} style={{ marginTop: "5cqw" }}>
        <div style={{ ...lede, fontSize: "9cqw", overflowWrap: "anywhere" }}>{first.name}</div>
        {kind !== "artist" && first.artist && <div style={{ ...sub, marginTop: "1cqw" }}>{first.artist}</div>}
      </Rise>
      <Rise i={3} style={{ marginTop: "3cqw" }}>
        <div style={{ fontSize: "5.2cqw", fontWeight: 800 }}>
          <b className="num" style={{ fontSize: "9cqw" }}><Num value={first.count} align="end" /></b>번 들었어요 <span style={{ ...sub, fontSize: "3.6cqw" }}>· 전체의 {pct(first.count, total)}%</span>
        </div>
      </Rise>
      <Rise i={4} style={{ marginTop: "4cqw" }}>
        <ol style={{ listStyle: "none", padding: 0, margin: 0, borderTop: "1px solid rgba(255,255,255,0.18)" }}>
          {items.slice(1, 5).map((it, i) => (
            <li key={`${it.artist}|${it.name}`} style={{ display: "flex", gap: "3cqw", alignItems: "baseline", padding: "1.6cqw 0", borderBottom: "1px solid rgba(255,255,255,0.1)", fontSize: "3.8cqw" }}>
              <b className="num" style={{ width: "4cqw", color: "rgba(255,255,255,0.55)" }}>{i + 2}</b>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.name}</span>
              <span className="num" style={{ fontWeight: 700 }}>{it.count.toLocaleString()}</span>
            </li>
          ))}
        </ol>
      </Rise>
    </>
  );
}

// ── 슬라이드 목록을 데이터에서 만든다 ──────────────────────────────

function buildSlides(year: number, d: Data, tints: Record<string, string>, partial: boolean): Slide[] {
  const out: Slide[] = [];
  const total = d.stats?.total_scrobbles ?? 0;

  out.push({
    key: "intro",
    tint: "#6a3fd1",
    node: (
      <>
        <Rise i={0}><div style={label}>Analyse Your Music</div></Rise>
        <Rise i={1} style={{ marginTop: "6cqw" }}><div style={{ ...huge, fontSize: "30cqw" }}>{year}</div></Rise>
        <Rise i={2} style={{ marginTop: "4cqw" }}><div style={{ ...huge, fontSize: "14cqw" }}>리플레이</div></Rise>
        <Rise i={3} style={{ marginTop: "8cqw" }}><div style={sub}>{partial ? `${year}년의 음악을 지금까지의 기록으로 돌아봐요.` : `${year}년에 들은 음악을 돌아봐요.`}</div></Rise>
      </>
    ),
  });

  if (d.time && d.stats && d.time.total_seconds > 0) {
    const hours = d.time.total_seconds / 3600;
    out.push({
      key: "time",
      tint: CAT.track.main,
      node: (
        <>
          <Rise i={0}><div style={label}>{year} · 청취 시간</div></Rise>
          <Rise i={1} style={{ marginTop: "6cqw" }}>
            <div style={lede}>{year}년에 음악을</div>
            <div style={{ ...huge, fontSize: "15cqw", marginTop: "2cqw", letterSpacing: "-0.03em" }}><NumUnits value={d.time.total_seconds} format={fmtHM} duration={1400} /></div>
            <div style={{ ...lede, marginTop: "2cqw" }}>들었어요.</div>
          </Rise>
          <Rise i={2} style={{ marginTop: "8cqw" }}>
            <div style={sub}>
              쉬지 않고 들으면 <b style={{ color: "#fff" }}>{Math.floor(hours / 24)}일 {Math.round(hours % 24)}시간</b>이에요. 스크로블은 <b style={{ color: "#fff" }}>{d.stats.total_scrobbles.toLocaleString()}번</b>이고, 하루 평균 <b style={{ color: "#fff" }}>{fmtHM(d.time.avg_seconds_per_day)}</b> 들었어요.
            </div>
          </Rise>
        </>
      ),
    });
  }

  (["artist", "album", "track"] as const).forEach((k) => {
    const items = d.top[k];
    if (!items.length) return;
    out.push({ key: k, tint: tints[k] ?? CAT[k === "artist" ? "artist" : k === "album" ? "album" : "track"].main, node: <TopSlide kind={k} items={items} total={total} year={year} /> });
  });

  if (d.months && d.months.counts.length >= 2) {
    const c = d.months.counts;
    const peak = c.indexOf(Math.max(...c));
    const active = c.filter((v) => v > 0);
    const avg = active.reduce((a, b) => a + b, 0) / Math.max(active.length, 1);
    const more = avg > 0 ? Math.round((c[peak] / avg - 1) * 100) : 0;
    out.push({
      key: "month",
      tint: CAT.album.main,
      node: (
        <>
          <Rise i={0}><div style={label}>{year} · 가장 몰입한 달</div></Rise>
          <Rise i={1} style={{ marginTop: "6cqw" }}>
            <div style={lede}>가장 많이 들은 달은</div>
            <div style={{ ...huge, fontSize: "26cqw", marginTop: "2cqw" }}>{Number(d.months.months[peak].slice(5))}월</div>
          </Rise>
          <Rise i={2} style={{ marginTop: "5cqw" }}>
            <div style={sub}>
              <b style={{ color: "#fff" }}>{c[peak].toLocaleString()}번</b> 들었어요.{more > 0 ? <> 달 평균보다 <b style={{ color: "#fff" }}>{more}%</b> 많아요.</> : null}
            </div>
          </Rise>
          <Rise i={3} style={{ marginTop: "8cqw" }}>
            <Bars values={c} hi={peak} color={CAT.album.main} labels={[`${Number(d.months.months[0].slice(5))}월`, `${Number(d.months.months[c.length - 1].slice(5))}월`]} />
          </Rise>
        </>
      ),
    });
  }

  if (d.hours && d.hours.length === 24) {
    const h = d.hours;
    const peak = h.indexOf(Math.max(...h));
    const sum = h.reduce((a, b) => a + b, 0) || 1;
    const bins = [
      { name: "새벽", persona: "올빼미형", share: h.slice(0, 6).reduce((a, b) => a + b, 0) / sum },
      { name: "오전", persona: "아침형", share: h.slice(6, 12).reduce((a, b) => a + b, 0) / sum },
      { name: "오후", persona: "낮형", share: h.slice(12, 18).reduce((a, b) => a + b, 0) / sum },
      { name: "저녁", persona: "저녁형", share: h.slice(18, 24).reduce((a, b) => a + b, 0) / sum },
    ];
    const top = bins.reduce((a, b) => (b.share > a.share ? b : a));
    out.push({
      key: "hour",
      tint: CAT.artist.main,
      node: (
        <>
          <Rise i={0}><div style={label}>{year} · 청취 시간대</div></Rise>
          <Rise i={1} style={{ marginTop: "6cqw" }}>
            <div style={lede}>가장 많이 들은 시간은</div>
            <div style={{ ...huge, fontSize: "22cqw", marginTop: "2cqw" }}>{hourKo(peak)}</div>
          </Rise>
          <Rise i={2} style={{ marginTop: "5cqw" }}>
            <div style={sub}>
              {top.name} 시간대가 전체의 <b style={{ color: "#fff" }}>{Math.round(top.share * 100)}%</b>예요. 당신은 <b style={{ color: "#fff" }}>{top.persona}</b> 리스너네요.
            </div>
          </Rise>
          <Rise i={3} style={{ marginTop: "8cqw" }}>
            <Bars values={h} hi={peak} color={CAT.artist.main} labels={["0시", "23시", "12시"]} />
          </Rise>
        </>
      ),
    });
  }

  if (d.time?.busiest_day) {
    const b = d.time.busiest_day;
    out.push({
      key: "day",
      tint: "#ff7a59",
      node: (
        <>
          <Rise i={0}><div style={label}>{year} · 가장 많이 들은 날</div></Rise>
          <Rise i={1} style={{ marginTop: "6cqw" }}>
            <div style={{ ...huge, fontSize: "12cqw", lineHeight: 1.1 }}>{longDate(b.date).replace(/^\d+년 /, "")}</div>
          </Rise>
          <Rise i={2} style={{ marginTop: "8cqw" }}>
            <div style={lede}>이날은 음악을 <b className="num">{fmtHM(b.seconds)}</b> 들었어요.</div>
          </Rise>
          <Rise i={3} style={{ marginTop: "4cqw" }}>
            <div style={sub}>하루에 <b style={{ color: "#fff" }}>{b.plays.toLocaleString()}번</b>을 재생했어요.</div>
          </Rise>
        </>
      ),
    });
  }

  if (d.newCounts && !d.isFirstYear && (d.newCounts.artist > 0 || d.newCounts.track > 0)) {
    out.push({
      key: "new",
      tint: "#3fb59a",
      node: (
        <>
          <Rise i={0}><div style={label}>{year} · 새로 만난 음악</div></Rise>
          <Rise i={1} style={{ marginTop: "6cqw" }}>
            <div style={lede}>올해 처음 만난 아티스트는</div>
            <div style={{ ...huge, fontSize: "24cqw", marginTop: "2cqw", letterSpacing: "-0.03em" }}><NumUnits value={d.newCounts.artist} format={(n) => `${Math.round(n).toLocaleString()}명`} duration={1400} /></div>
          </Rise>
          <Rise i={2} style={{ marginTop: "7cqw" }}>
            <div style={sub}>
              앨범 <b style={{ color: "#fff" }}>{d.newCounts.album.toLocaleString()}개</b>, 트랙 <b style={{ color: "#fff" }}>{d.newCounts.track.toLocaleString()}곡</b>도 처음 들었어요.
            </div>
          </Rise>
        </>
      ),
    });
  }

  if (d.tags.length > 0) {
    const tags = d.tags.slice(0, 5);
    const max = tags[0].score || 1;
    out.push({
      key: "tags",
      tint: "#c490ff",
      node: (
        <>
          <Rise i={0}><div style={label}>{year} · 장르</div></Rise>
          <Rise i={1} style={{ marginTop: "6cqw" }}>
            <div style={lede}>가장 많이 들은 장르는</div>
            <div style={{ ...huge, fontSize: "14cqw", marginTop: "2cqw", overflowWrap: "anywhere" }}>{tags[0].tag}</div>
          </Rise>
          <Rise i={2} style={{ marginTop: "8cqw" }}>
            {tags.map((t, i) => (
              <div key={t.tag} style={{ display: "flex", alignItems: "center", gap: "3cqw", margin: "2.4cqw 0", fontSize: "3.8cqw" }}>
                <b className="num" style={{ width: "4cqw", color: "rgba(255,255,255,0.55)" }}>{i + 1}</b>
                <span style={{ width: "28cqw", flexShrink: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.tag}</span>
                <div style={{ flex: 1, height: "2.6cqw", borderRadius: "1.3cqw", background: "rgba(255,255,255,0.14)" }}>
                  <div className="aym-bar" style={{ width: `${(t.score / max) * 100}%`, height: "100%", borderRadius: "1.3cqw", background: "#fff", animationDelay: `${400 + i * 120}ms` }} />
                </div>
              </div>
            ))}
          </Rise>
        </>
      ),
    });
  }

  // 마지막: 한눈에 요약 + 공유
  out.push({
    key: "outro",
    tint: "#fa233b",
    node: (
      <>
        <Rise i={0}><div style={label}>{year} 리플레이</div></Rise>
        <Rise i={1} style={{ marginTop: "5cqw" }}>
          <div style={lede}>{year}년의 음악을 한눈에</div>
        </Rise>
        <Rise i={2} style={{ marginTop: "6cqw" }}>
          <div className="aym-story-recap">
            {d.top.artist[0] && <div><small>아티스트</small><b>{d.top.artist[0].name}</b></div>}
            {d.top.album[0] && <div><small>앨범</small><b>{d.top.album[0].name}</b></div>}
            {d.top.track[0] && <div><small>트랙</small><b>{d.top.track[0].name}</b></div>}
            {d.time && <div><small>청취 시간</small><b>{fmtHM(d.time.total_seconds)}</b></div>}
            {d.stats && <div><small>스크로블</small><b>{d.stats.total_scrobbles.toLocaleString()}번</b></div>}
          </div>
        </Rise>
        <Rise i={3} style={{ marginTop: "7cqw", display: "flex", gap: "2cqw", flexWrap: "wrap" }}>
          <ShareButton spec={{ kind: "period", card: "summary", period: "year", anchor: String(year) }} label="🖼 공유 이미지 만들기" />
        </Rise>
      </>
    ),
  });

  return out;
}

// ── 뷰어 ────────────────────────────────────────────────────────────

export function ReplayStory({ year, onClose }: { year: number; onClose: () => void }) {
  const [data, setData] = useState<Data | null>(null);
  const [tints, setTints] = useState<Record<string, string>>({});
  const [index, setIndex] = useState(0);
  const [paused, setPaused] = useState(false);
  const pressedAt = useRef(0);
  const partial = year === new Date().getFullYear();

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setIndex(0);
    loadYear(year).then((d) => !cancelled && setData(d));
    return () => {
      cancelled = true;
    };
  }, [year]);

  // TOP 슬라이드 배경색: 1위 커버의 대표색
  useEffect(() => {
    if (!data) return;
    let cancelled = false;
    (["artist", "album", "track"] as const).forEach((k) => {
      const first = data.top[k][0];
      if (!first) return;
      const p = k === "artist" ? cover("artist", first.name) : cover("album", first.artist, k === "album" ? first.name : first.album);
      p.then((img) => {
        const c = img ? dominantColor(img) : null;
        if (!cancelled && c) setTints((t) => ({ ...t, [k]: c }));
      });
    });
    return () => {
      cancelled = true;
    };
  }, [data]);

  const slides = useMemo(() => (data ? buildSlides(year, data, tints, partial) : []), [data, tints, year, partial]);
  const last = slides.length - 1;
  const next = useCallback(() => setIndex((i) => Math.min(i + 1, Math.max(last, 0))), [last]);
  const prev = useCallback(() => setIndex((i) => Math.max(i - 1, 0)), []);

  // 키보드와 배경 스크롤 잠금
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
      else if (e.key === "ArrowRight" || e.key === " ") {
        e.preventDefault();
        next();
      } else if (e.key === "ArrowLeft") prev();
    };
    window.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [next, prev, onClose]);

  const slide = slides[index];
  const tapZone = (dir: "prev" | "next") => (e: React.MouseEvent) => {
    e.stopPropagation();
    if (Date.now() - pressedAt.current > 300) return;     // 길게 누른 것(멈춤)은 이동으로 치지 않는다
    if (dir === "next") next();
    else prev();
  };

  return (
    <div className="aym-story-back" role="dialog" aria-modal="true" aria-label={`${year} 리플레이`} onClick={onClose}>
      <button className="aym-story-nav left" onClick={(e) => { e.stopPropagation(); prev(); }} aria-label="이전" disabled={index === 0}>‹</button>
      <div
        className="aym-story"
        onClick={(e) => e.stopPropagation()}
        onPointerDown={() => {
          pressedAt.current = Date.now();
          setPaused(true);
        }}
        onPointerUp={() => setPaused(false)}
        onPointerLeave={() => setPaused(false)}
        onPointerCancel={() => setPaused(false)}
        style={{ ["--tint" as string]: slide?.tint ?? "#444", ["--dur" as string]: `${SLIDE_MS}ms` }}
      >
        {/* 진행 막대 */}
        <div className="aym-story-bars" aria-hidden>
          {slides.map((s, i) => (
            <i key={s.key} className={i < index ? "done" : i === index ? "on" : undefined}>
              <b
                key={i === index ? `on${index}` : "x"}
                style={i === index && paused ? { animationPlayState: "paused" } : undefined}
                onAnimationEnd={i === index && i < last ? next : undefined}
              />
            </i>
          ))}
        </div>
        <button className="aym-story-close" onClick={onClose} aria-label="닫기">✕</button>

        {!data ? (
          <div className="aym-story-slide" key="loading">
            <div style={label}>{year} 리플레이</div>
            <div style={{ ...lede, marginTop: "6cqw", color: "rgba(255,255,255,0.6)" }}>한 해의 기록을 모으는 중…</div>
          </div>
        ) : slides.length === 0 ? (
          <div className="aym-story-slide" key="empty">
            <div style={lede}>{year}년에는 기록이 없어요.</div>
          </div>
        ) : (
          <div className="aym-story-slide" key={slide.key}>
            {slide.node}
          </div>
        )}

        {/* 탭 영역: 왼쪽 1/3 은 이전, 오른쪽 2/3 는 다음 (공유 버튼 등은 이 위에 떠서 눌린다) */}
        <div className="aym-story-tap left" onClick={tapZone("prev")} />
        <div className="aym-story-tap right" onClick={tapZone("next")} />
      </div>
      <button className="aym-story-nav right" onClick={(e) => { e.stopPropagation(); next(); }} aria-label="다음" disabled={!data || index >= last}>›</button>
    </div>
  );
}

// ── 시작 버튼: [연도 ▾] [🎬 리플레이] ───────────────────────────────

export function ReplayButton() {
  const [years, setYears] = useState<number[]>([]);
  const [year, setYear] = useState<number | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getJson<{ years: number[] }>(`/api/listening/yearly`).then((d) => {
      if (cancelled || !d?.years?.length) return;
      setYears(d.years);
      setYear(d.years[d.years.length - 1]);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (!years.length || year === null) return null;
  return (
    <>
      <div className="aym-seg" role="group" aria-label="리플레이">
        {years.length > 1 && (
          <select
            value={year}
            onChange={(e) => setYear(Number(e.target.value))}
            aria-label="리플레이 연도"
            style={{ background: "transparent", border: 0, padding: "0.3rem 0.4rem 0.3rem 0.8rem", fontWeight: 700, fontSize: "0.88rem", borderRadius: 999 }}
          >
            {[...years].reverse().map((y) => (
              <option key={y} value={y}>{y}</option>
            ))}
          </select>
        )}
        <button onClick={() => setOpen(true)} style={{ background: "var(--key)", color: "#fff" }}>🎬 리플레이</button>
      </div>
      {/* 문서 맨 바깥에 그린다: 제목줄 안에 두면 제목줄의 글자 스타일(회색·다른 글꼴)이 스토리 안으로 상속된다 */}
      {open && createPortal(<ReplayStory year={year} onClose={() => setOpen(false)} />, document.body)}
    </>
  );
}
