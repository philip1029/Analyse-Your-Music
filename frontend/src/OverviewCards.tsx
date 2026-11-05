import { useEffect, useState } from "react";
import { BASE_URL } from "./config";
import { fmtHM, longDate } from "./format";
import { Num, Skeleton, stagger } from "./motion";
import { CAT, MUTED, SCROBBLE_COLOR } from "./theme";

// 요약 구역 맨 위: 문장 해설(리플레이식) → 핵심 수치 칩 → 증감 칩이 있는 통계 타일 4개.
// 문장·수치는 모두 받아 둔 데이터에서 규칙으로 계산한다 (AI 없음).

type CardData = { value: number; delta_pct: number | null; prev: number; bars: number[] };
type Cards = { mode: "range" | "recent"; label: string; delta_label: string; cards: Record<"scrobbles" | "artists" | "albums" | "tracks", CardData> };

type TimeSummary = {
  total_seconds: number;
  coverage: number;
  days: number;
  active_days: number;
  avg_seconds_per_day: number;
  busiest_day: { date: string; seconds: number; plays: number } | null;
};

function Bars({ bars, color }: { bars: number[]; color: string }) {
  const max = Math.max(...bars, 1);
  const w = 5;
  const gap = 3;
  const H = 30;
  return (
    <svg width={bars.length * (w + gap) - gap} height={H} aria-hidden style={{ position: "absolute", right: 16, top: 16 }}>
      {bars.map((b, i) => {
        const h = Math.max(3, (b / max) * H);
        return <rect key={i} className="aym-spark" style={{ animationDelay: `${120 + i * 60}ms` }} x={i * (w + gap)} y={H - h} width={w} height={h} rx={2.5} fill={color} opacity={0.9} />;
      })}
    </svg>
  );
}

// 어두운 유리 타일: 카테고리 색 점 · 큰 숫자 · 증감 칩 · 오른쪽 위 미니 막대
function StatCard({ title, color, data, sub, deltaTitle, index = 0 }: { title: string; color: string; data: CardData; sub: string; deltaTitle: string; index?: number }) {
  const d = data.delta_pct;
  return (
    <div className="aym-rise aym-panel" style={{ ...stagger(index, 70), position: "relative", overflow: "hidden", padding: "16px 16px 14px" }}>
      <Bars key={data.bars.join(",")} bars={data.bars} color={color} />
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.9rem", fontWeight: 600, color: "var(--text-2)" }}>
        <i style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />
        {title}
      </div>
      <div className="num" style={{ fontSize: "clamp(2rem, 4vw, 2.7rem)", fontWeight: 800, lineHeight: 1.05, margin: "0.5rem 0 0.4rem", whiteSpace: "nowrap" }}>
        <Num value={data.value} />
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 6, minHeight: "1.5rem", flexWrap: "wrap" }}>
        {d !== null && (
          <span
            title={`${deltaTitle} (비교 대상 ${data.prev.toLocaleString()})`}
            style={{ display: "inline-block", fontSize: "0.8rem", fontWeight: 700, padding: "2px 9px", borderRadius: 999, color, background: `color-mix(in srgb, ${color} 16%, transparent)` }}
          >
            {d >= 0 ? "↑" : "↓"} <Num value={Math.abs(Math.round(d))} duration={900} />%
          </span>
        )}
        <span style={{ fontSize: "0.78rem", color: "var(--text-3)" }}>{sub}</span>
      </div>
    </div>
  );
}

function plain(date: string): string {
  const [y, m, d] = date.slice(0, 10).split("-");
  return `${y}년 ${Number(m)}월 ${Number(d)}일`;
}

export function OverviewCards({
  query,
  firstScrobble,
  totalScrobbles,
  timeSummary,
  isAllTime,
}: {
  query: (extra?: Record<string, string | number>) => string;
  firstScrobble: string | null;
  totalScrobbles: number;
  timeSummary: TimeSummary | null;
  isAllTime: boolean;
}) {
  const [data, setData] = useState<Cards | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${BASE_URL}/api/overview/cards${query()}`)
      .then((r) => r.json())
      .then((d) => !cancelled && setData(d.error ? null : (d as Cards)))
      .catch(() => !cancelled && setData(null));
    return () => {
      cancelled = true;
    };
  }, [query]);

  const scrobbleDelta = data?.cards.scrobbles.delta_pct ?? null;
  const perDay = timeSummary && timeSummary.days > 0 ? Math.round(totalScrobbles / timeSummary.days) : null;
  const shortDelta = data ? (data.delta_label.split("·").pop() ?? "").trim() : "";

  return (
    <>
      {/* 문장 해설: 숫자만 또렷하게 */}
      {timeSummary ? (
        <div key={`${isAllTime}-${Math.round(timeSummary.total_seconds)}`}>
          {isAllTime ? (
            <p className="aym-lede aym-rise">
              {firstScrobble ? <><b>{plain(firstScrobble)}</b>부터 </> : null}
              <b className="num"><Num value={totalScrobbles} duration={1100} align="end" /></b>번 들었고,<br />음악을{" "}
              <b className="num"><Num value={timeSummary.total_seconds} format={fmtHM} duration={1100} align="end" /></b> 들었어요.
            </p>
          ) : (
            <p className="aym-lede aym-rise">
              이 기간에 음악을 <b className="num"><Num value={timeSummary.total_seconds} format={fmtHM} duration={1100} align="end" /></b> 들었어요.
              {scrobbleDelta !== null && (
                <><br />직전 같은 기간보다 스크로블이 <b className="num"><Num value={Math.abs(Math.round(scrobbleDelta))} align="end" />%</b> {scrobbleDelta >= 0 ? "늘었어요" : "줄었어요"}.</>
              )}
            </p>
          )}

          {/* 핵심 수치 칩 */}
          <div className="aym-facts aym-rise" style={{ animationDelay: "140ms" }}>
            <div className="aym-fact"><small>하루 평균</small><b><Num value={timeSummary.avg_seconds_per_day} format={fmtHM} /></b></div>
            {timeSummary.busiest_day && (
              <div className="aym-fact"><small>가장 많이 들은 날</small><b>{longDate(timeSummary.busiest_day.date)}<em>{fmtHM(timeSummary.busiest_day.seconds)}</em></b></div>
            )}
            <div className="aym-fact"><small>기록한 날</small><b>{timeSummary.active_days.toLocaleString()}<em>/ {timeSummary.days.toLocaleString()}일</em></b></div>
            {perDay !== null && <div className="aym-fact"><small>하루 평균 재생</small><b>{perDay.toLocaleString()}<em>번</em></b></div>}
          </div>
          <p style={{ color: "var(--text-3)", fontSize: "0.78rem", marginTop: 8 }}>
            청취 시간은 스크로블 × 곡 길이로 추정한 값이에요 · 길이를 아는 재생 {Math.round(timeSummary.coverage * 100)}% 기준
          </p>
        </div>
      ) : (
        <Skeleton lines={2} height={34} style={{ margin: "1rem 0 1.4rem" }} />
      )}

      {/* 통계 타일: 스크로블 · 아티스트 · 앨범 · 트랙 */}
      {data && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: "0.8rem", marginTop: "1.6rem" }}>
            <StatCard title="스크로블" color={SCROBBLE_COLOR} data={data.cards.scrobbles} sub={perDay !== null ? `하루 평균 ${perDay}회` : shortDelta} deltaTitle={data.delta_label} index={0} />
            <StatCard title={CAT.artist.label} color={CAT.artist.main} data={data.cards.artists} sub={shortDelta} deltaTitle={data.delta_label} index={1} />
            <StatCard title={CAT.album.label} color={CAT.album.main} data={data.cards.albums} sub={shortDelta} deltaTitle={data.delta_label} index={2} />
            <StatCard title={CAT.track.label} color={CAT.track.main} data={data.cards.tracks} sub={shortDelta} deltaTitle={data.delta_label} index={3} />
          </div>
          <p style={{ color: MUTED, fontSize: "0.78rem", margin: "0.6rem 0 0" }}>
            {isAllTime ? "숫자는 전체 기간 합계" : `숫자는 ${data.label} 합계`} · 화살표는 {data.delta_label} 증감 · 막대는 {data.mode === "recent" ? "최근 6개월" : "기간을 6등분한 구간"}별 값
          </p>
        </>
      )}
    </>
  );
}

// 증감 없이 값만 보여 주는 카테고리 색 타일 (발견 구역 등에서 쓴다)
export function CatStat({ title, color, value, unit }: { title: string; color: string; value: number; unit?: string }) {
  return (
    <div className="aym-panel" style={{ padding: "16px 16px 14px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.9rem", fontWeight: 600, color: "var(--text-2)" }}>
        <i style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />
        {title}
      </div>
      <div style={{ marginTop: "0.5rem", display: "flex", alignItems: "baseline", gap: "0.3rem" }}>
        <span className="num" style={{ fontSize: "clamp(2rem, 4vw, 2.7rem)", fontWeight: 800, lineHeight: 1 }}><Num value={value} /></span>
        {unit && <span style={{ fontSize: "1rem", fontWeight: 600, color: "var(--text-2)" }}>{unit}</span>}
      </div>
    </div>
  );
}
