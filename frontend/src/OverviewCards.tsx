import { useEffect, useState, type CSSProperties } from "react";
import { BASE_URL } from "./config";
import { fmtHM, withWeekday } from "./format";
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
  const w = 8;
  const gap = 5;
  return (
    <svg width={bars.length * (w + gap) - gap} height={36} aria-hidden style={{ flexShrink: 0 }}>
      {bars.map((b, i) => {
        const h = Math.max(3, (b / max) * 36);
        return <rect key={i} x={i * (w + gap)} y={36 - h} width={w} height={h} fill={CARD_INK} />;
      })}
    </svg>
  );
}

function StatCard({ title, color, data, deltaTitle }: { title: string; color: string; data: CardData; deltaTitle: string }) {
  const d = data.delta_pct;
  return (
    <div style={{ background: color, color: CARD_INK, clipPath: DOG_EAR, padding: "0.9rem 1.1rem 1rem", minHeight: 104, textAlign: "left" }}>
      <div style={{ fontSize: "0.95rem", fontWeight: 600 }}>{title}</div>
      <div style={{ display: "flex", alignItems: "flex-end", justifyContent: "space-between", gap: "0.6rem", marginTop: "0.5rem" }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: "0.5rem", flexWrap: "wrap" }}>
          <span style={{ fontSize: "2.3rem", fontWeight: 800, lineHeight: 1 }}>{data.value.toLocaleString()}</span>
          {d !== null && (
            <span title={`${deltaTitle} (비교 대상 ${data.prev.toLocaleString()})`} style={{ fontSize: "0.95rem", fontWeight: 700 }}>
              {d >= 0 ? "↑" : "↓"} {Math.abs(Math.round(d))}%
            </span>
          )}
        </div>
        <Bars bars={data.bars} />
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
        <div style={{ margin: "0.6rem 0 1.4rem" }}>
          {isAllTime ? (
            <p style={sentenceBase}>
              {firstScrobble ? <><span style={strong}>{plain(firstScrobble)}</span>부터 </> : null}
              <span style={strong}>{totalScrobbles.toLocaleString()}</span>번 들었고, 음악을{" "}
              <span style={strong}>{fmtHM(timeSummary.total_seconds)}</span> 들었어요.
            </p>
          ) : (
            <p style={sentenceBase}>
              이 기간에 음악을 <span style={strong}>{fmtHM(timeSummary.total_seconds)}</span> 들었어요.
              {scrobbleDelta !== null && (
                <> 직전 같은 기간보다 스크로블이 <span style={strong}>{Math.abs(Math.round(scrobbleDelta))}%</span> {scrobbleDelta >= 0 ? "늘었어요" : "줄었어요"}.</>
              )}
            </p>
          )}
          <p style={{ ...sentenceBase, fontSize: "1.05rem", fontWeight: 500, margin: 0 }}>
            하루 평균 <span style={strong}>{fmtHM(timeSummary.avg_seconds_per_day)}</span>
            {timeSummary.busiest_day && (
              <>
                , 가장 많이 들은 날은 <span style={strong}>{withWeekday(timeSummary.busiest_day.date)}</span>({fmtHM(timeSummary.busiest_day.seconds)})
              </>
            )}
            였어요.
            <span style={{ fontSize: "0.8rem", marginLeft: "0.5rem" }}>(스크로블 × 곡 길이 추정 · 길이를 아는 재생 {Math.round(timeSummary.coverage * 100)}% 기준)</span>
          </p>
        </div>
      )}

      {/* 통계 카드: 스크로블(분홍) · 아티스트(보라) · 앨범(민트) · 트랙(파랑) */}
      {data && (
        <>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(210px, 1fr))", gap: "0.8rem" }}>
            <StatCard title="스크로블" color={SCROBBLE_COLOR} data={data.cards.scrobbles} deltaTitle={data.delta_label} />
            <StatCard title={CAT.artist.label} color={CAT.artist.main} data={data.cards.artists} deltaTitle={data.delta_label} />
            <StatCard title={CAT.album.label} color={CAT.album.main} data={data.cards.albums} deltaTitle={data.delta_label} />
            <StatCard title={CAT.track.label} color={CAT.track.main} data={data.cards.tracks} deltaTitle={data.delta_label} />
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
