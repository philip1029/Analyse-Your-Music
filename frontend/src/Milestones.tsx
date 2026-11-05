import { useEffect, useState } from "react";
import { BASE_URL } from "./config";
import { Reveal, Num } from "./motion";
import { CAT, SCROBBLE_COLOR } from "./theme";
import { etaDate, isoDay, nextMilestone, untilText, ymd, type Milestone } from "./milestoneRules";

// 요약 구역의 "다음 이정표": 스크로블·청취 시간·아티스트 수가 다음 "딱 떨어지는" 숫자(5,000 · 10,000 · 50,000 …)까지 얼마나 남았고,
// 최근 30일 속도라면 언제쯤 닿는지. 기간 선택과 무관하게 전체 기록 기준이고, 모두 이미 받은 데이터에서 규칙으로 계산한다 (AI 없음).

type Stats = { total_scrobbles: number; unique_artists: number };
type TimeSummary = { total_seconds: number };
type Disc = { artist: { months: string[]; counts: number[] } };

const getJson = <T,>(path: string): Promise<T | null> =>
  fetch(`${BASE_URL}${path}`)
    .then((r) => r.json())
    .then((d) => (d && !d.error ? (d as T) : null))
    .catch(() => null);

type Row = { key: string; label: string; unit: string; color: string; ms: Milestone; fmt: (n: number) => string; paceText: string };

export function Milestones() {
  const [rows, setRows] = useState<Row[] | null>(null);
  const [today] = useState(() => new Date());

  useEffect(() => {
    let cancelled = false;
    const end = isoDay(today);
    const from = new Date(today);
    from.setDate(from.getDate() - 29);
    const r30 = `start=${isoDay(from)}&end=${end}`;
    Promise.all([
      getJson<Stats>(`/api/stats`),
      getJson<TimeSummary>(`/api/time/summary`),
      getJson<Stats>(`/api/stats?${r30}`),
      getJson<TimeSummary>(`/api/time/summary?${r30}`),
      getJson<Disc>(`/api/discovery/summary`),
    ]).then(([all, allTime, recent, recentTime, disc]) => {
      if (cancelled || !all) return;
      const out: Row[] = [];

      const playsPerDay = recent ? recent.total_scrobbles / 30 : null;
      out.push({
        key: "scrobbles",
        label: "스크로블",
        unit: "번",
        color: SCROBBLE_COLOR,
        ms: nextMilestone(all.total_scrobbles, playsPerDay),
        fmt: (n) => n.toLocaleString(),
        paceText: playsPerDay ? `하루 ${Math.round(playsPerDay).toLocaleString()}번` : "",
      });

      if (allTime && allTime.total_seconds > 0) {
        const hoursPerDay = recentTime ? recentTime.total_seconds / 3600 / 30 : null;
        out.push({
          key: "hours",
          label: "청취 시간",
          unit: "시간",
          color: CAT.album.main,
          ms: nextMilestone(Math.floor(allTime.total_seconds / 3600), hoursPerDay),
          fmt: (n) => n.toLocaleString(),
          paceText: hoursPerDay ? `하루 ${hoursPerDay.toFixed(1)}시간` : "",
        });
      }

      // 새 아티스트는 마지막 완료된 3개월의 월평균으로 속도를 잡는다 (진행 중인 달은 뺀다)
      let artistsPerDay: number | null = null;
      if (disc) {
        const thisMonth = isoDay(today).slice(0, 7);
        const { months, counts } = disc.artist;
        const done = months.length && months[months.length - 1] === thisMonth ? counts.slice(0, -1) : counts;
        const last3 = done.slice(-3);
        if (last3.length >= 2) artistsPerDay = last3.reduce((a, b) => a + b, 0) / last3.length / 30.4;
      }
      out.push({
        key: "artists",
        label: "아티스트",
        unit: "명",
        color: CAT.artist.main,
        ms: nextMilestone(all.unique_artists, artistsPerDay),
        fmt: (n) => n.toLocaleString(),
        paceText: artistsPerDay ? `새 아티스트 하루 ${artistsPerDay.toFixed(1)}명` : "",
      });
      setRows(out);
    });
    return () => {
      cancelled = true;
    };
  }, [today]);

  if (!rows || rows.length === 0) return null;
  const first = rows[0];

  return (
    <>
      <div className="aym-h3">
        <h3>다음 이정표</h3>
        <span>전체 기록 기준 · 예상은 최근 30일 속도로 계산해요</span>
      </div>
      <p className="aym-lede xs">
        {first.label} <b className="num">{first.ms.target.toLocaleString()}{first.unit}째</b>까지 <b className="num">{first.ms.remaining.toLocaleString()}{first.unit}</b> 남았어요.
        {first.ms.days !== null ? (
          <> 지금 속도라면 <b>{untilText(first.ms.days)}</b>, <b>{ymd(etaDate(today, first.ms.days))}</b>쯤이에요.</>
        ) : (
          <> 최근 기록이 적어서 도달 시점은 예상하기 어려워요.</>
        )}
      </p>
      <Reveal minHeight={170}>
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))", gap: 12, marginTop: 16 }}>
          {rows.map((r) => (
            <div key={r.key} className="aym-panel" style={{ padding: "16px 18px" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: "0.9rem", fontWeight: 600, color: "var(--text-2)" }}>
                <i style={{ width: 8, height: 8, borderRadius: "50%", background: r.color, display: "inline-block" }} />
                {r.label}
                <span style={{ marginLeft: "auto", fontSize: "0.78rem", color: "var(--text-3)" }}>다음 {r.fmt(r.ms.target)}{r.unit}</span>
              </div>
              <div className="num" style={{ fontSize: "1.9rem", fontWeight: 800, lineHeight: 1.1, margin: "0.45rem 0 0.7rem" }}>
                <Num value={r.ms.current} format={(n) => Math.round(n).toLocaleString()} />
                <small style={{ fontFamily: "var(--font)", fontSize: "0.85rem", fontWeight: 600, color: "var(--text-3)", marginLeft: 6 }}>{r.unit}</small>
              </div>
              <div style={{ height: 8, borderRadius: 4, background: "var(--surface-2)", overflow: "hidden" }} title={`${r.fmt(r.ms.prev)} → ${r.fmt(r.ms.target)}`}>
                <div className="aym-bar" style={{ width: `${Math.max(2, r.ms.progress * 100)}%`, height: "100%", borderRadius: 4, background: r.color }} />
              </div>
              <div style={{ display: "flex", justifyContent: "space-between", fontSize: "0.75rem", color: "var(--text-3)", marginTop: 5 }}>
                <span>{r.fmt(r.ms.prev)}</span>
                <span>{Math.round(r.ms.progress * 100)}%</span>
                <span>{r.fmt(r.ms.target)}</span>
              </div>
              <div style={{ fontSize: "0.82rem", color: "var(--text-2)", marginTop: 8, lineHeight: 1.5 }}>
                {r.ms.remaining.toLocaleString()}{r.unit} 남음
                {r.ms.days !== null ? <> · {untilText(r.ms.days)}{r.paceText ? <span style={{ color: "var(--text-3)" }}> ({r.paceText})</span> : null}</> : <span style={{ color: "var(--text-3)" }}> · 예상 어려움</span>}
              </div>
            </div>
          ))}
        </div>
      </Reveal>
    </>
  );
}
