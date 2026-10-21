import { useEffect, useState, type CSSProperties } from "react";
import { BASE_URL } from "./config";
import { fmtHM, longDate } from "./format";
import { Num, Skeleton, stagger } from "./motion";
import { CAT, CARD_INK, DOG_EAR, MUTED, SCROBBLE_COLOR } from "./theme";

// Overview 맨 위: 문장형 요약(Apple 리플레이식) + 증감 칩이 있는 통계 카드 4개(Last.fm 리포트식)

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

// 강조할 숫자: 보조색 문장 안에서 페이지 기본 글자색(다크면 흰색, 라이트면 검정)으로
const strong: CSSProperties = { fontWeight: 800, color: "CanvasText" };

function Bars({ bars }: { bars: number[] }) {
  const max = Math.max(...bars, 1);
  const w = 6;
  const gap = 4;
  return (
    <svg width={bars.length * (w + gap) - gap} height={36} aria-hidden style={{ flexShrink: 0 }}>
      {bars.map((b, i) => {
        const h = Math.max(3, (b / max) * 36);
        return <rect key={i} className="aym-spark" style={{ animationDelay: `${120 + i * 60}ms` }} x={i * (w + gap)} y={36 - h} width={w} height={h} fill={CARD_INK} />;
      })}
    </svg>
  );
}

function StatCard({ title, color, data, deltaTitle, index = 0 }: { title: string; color: string; data: CardData; deltaTitle: string; index?: number }) {
  const d = data.delta_pct;
  return (
    <div className="aym-rise" style={{ ...stagger(index, 70), background: color, color: CARD_INK, clipPath: DOG_EAR, padding: "0.9rem 1.1rem 1rem", minHeight: 124, textAlign: "left" }}>
      <div style={{ fontSize: "0.95rem", fontWeight: 600 }}>{title}</div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: "0.6rem", marginTop: "0.5rem", flexWrap: "wrap" }}>
        {/* 모든 카드가 같은 배치: 큰 숫자 · 그 아래 증감 칩(없어도 한 줄 자리를 남김) · 오른쪽 아래 막대 */}
        <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem", minWidth: 0 }}>
          <span style={{ fontSize: "2.3rem", fontWeight: 800, lineHeight: 1, whiteSpace: "nowrap" }}><Num value={data.value} /></span>
          <span title={d !== null ? `${deltaTitle} (비교 대상 ${data.prev.toLocaleString()})` : undefined} style={{ fontSize: "0.95rem", fontWeight: 700, lineHeight: "1.2rem", minHeight: "1.2rem" }}>
            {d !== null && (
              <>
                {d >= 0 ? "↑" : "↓"} <Num value={Math.abs(Math.round(d))} duration={900} />%
              </>
            )}
          </span>
        </div>
        <Bars key={data.bars.join(",")} bars={data.bars} />
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
  const sentenceBase: CSSProperties = { fontSize: "clamp(1.5rem, 3.2vw, 2.1rem)", fontWeight: 700, lineHeight: 1.35, color: MUTED, margin: "0.4rem 0 0.4rem", textAlign: "left" };

  return (
    <>
      {/* 문장형 요약: 숫자만 굵게 강조한다 */}
      {timeSummary && (
        <div key={`${isAllTime}-${Math.round(timeSummary.total_seconds)}`} style={{ margin: "0.6rem 0 1.4rem" }}>
          {isAllTime ? (
            <p className="aym-rise" style={sentenceBase}>
              {firstScrobble ? <><span style={strong}>{plain(firstScrobble)}</span>부터 </> : null}
              <span style={strong}><Num value={totalScrobbles} duration={1100} /></span>번 들었고,<br />음악을{" "}
              <span style={strong}><Num value={timeSummary.total_seconds} format={fmtHM} duration={1100} /></span> 들었어요.
            </p>
          ) : (
            <p className="aym-rise" style={sentenceBase}>
              이 기간에 음악을 <span style={strong}><Num value={timeSummary.total_seconds} format={fmtHM} duration={1100} /></span> 들었어요.
              {scrobbleDelta !== null && (
                <><br />직전 같은 기간보다 스크로블이 <span style={strong}><Num value={Math.abs(Math.round(scrobbleDelta))} />%</span> {scrobbleDelta >= 0 ? "늘었어요" : "줄었어요"}.</>
              )}
            </p>
          )}
          <p className="aym-rise" style={{ ...sentenceBase, fontSize: "1.05rem", fontWeight: 500, margin: 0, animationDelay: "140ms" }}>
            하루 평균 <span style={strong}><Num value={timeSummary.avg_seconds_per_day} format={fmtHM} /></span>
            {timeSummary.busiest_day ? (
              <>
                이고, 가장 많이 들은 날은 <span style={strong}>{longDate(timeSummary.busiest_day.date)}</span>로{" "}
                <span style={strong}>{fmtHM(timeSummary.busiest_day.seconds)}</span>
              </>
            ) : null}
            이었어요.
            <span style={{ fontSize: "0.8rem", marginLeft: "0.5rem" }}>(스크로블 × 곡 길이 추정 · 길이를 아는 재생 {Math.round(timeSummary.coverage * 100)}% 기준)</span>
          </p>
        </div>
      )}

      {!timeSummary && <Skeleton lines={2} height={30} style={{ margin: "0.6rem 0 1.4rem" }} />}

      {/* 통계 카드: 스크로블(분홍) · 아티스트(보라) · 앨범(민트) · 트랙(파랑) */}
      {data && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: "0.8rem" }}>
            <StatCard title="스크로블" color={SCROBBLE_COLOR} data={data.cards.scrobbles} deltaTitle={data.delta_label} index={0} />
            <StatCard title={CAT.artist.label} color={CAT.artist.main} data={data.cards.artists} deltaTitle={data.delta_label} index={1} />
            <StatCard title={CAT.album.label} color={CAT.album.main} data={data.cards.albums} deltaTitle={data.delta_label} index={2} />
            <StatCard title={CAT.track.label} color={CAT.track.main} data={data.cards.tracks} deltaTitle={data.delta_label} index={3} />
          </div>
          <p style={{ color: MUTED, fontSize: "0.8rem", textAlign: "left", margin: "0.5rem 0 1rem" }}>
            {isAllTime ? "숫자는 전체 기간 합계" : `숫자는 ${data.label} 합계`} · 화살표는 {data.delta_label}
            {data.mode === "recent" ? " 증감" : " 증감"} · 막대는 {data.mode === "recent" ? "최근 6개월" : "기간을 6등분한 구간"}별 값
          </p>
        </>
      )}
    </>
  );
}

// 증감 없이 값만 보여 주는 카테고리 색 카드 (Discovery 등에서 쓴다)
export function CatStat({ title, color, value, unit }: { title: string; color: string; value: number; unit?: string }) {
  return (
    <div style={{ background: color, color: CARD_INK, clipPath: DOG_EAR, padding: "0.9rem 1.1rem 1rem", minHeight: 88, textAlign: "left" }}>
      <div style={{ fontSize: "0.95rem", fontWeight: 600 }}>{title}</div>
      <div style={{ marginTop: "0.4rem", display: "flex", alignItems: "baseline", gap: "0.3rem" }}>
        <span style={{ fontSize: "2.3rem", fontWeight: 800, lineHeight: 1 }}><Num value={value} /></span>
        {unit && <span style={{ fontSize: "1rem", fontWeight: 600 }}>{unit}</span>}
      </div>
    </div>
  );
}
