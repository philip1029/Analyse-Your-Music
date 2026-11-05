import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BASE_URL } from "./config";
import { LINE } from "./RankRow";
import { MUTED } from "./theme";

// 장르/태그 분포: 평소에는 지금 고른 기간의 분포 하나, 비교 월을 고르면 그 달의 분포를 같은 축에 겹쳐 그린다.
// 두 기간은 재생 수가 달라서 점수 대신 "그 기간 전체 태그 점수에서 차지하는 비율(%)"로 맞춰 비교한다.

export type TagDistribution = {
  tags: { tag: string; score: number }[];
  covered_artists: number;
  total_artists: number;
  covered_plays: number;
  total_plays: number;
};
type Coverage = Pick<TagDistribution, "covered_artists" | "total_artists" | "covered_plays" | "total_plays">;
type Compare = { error?: string; tags: { tag: string; base: number; compare: number; base_score: number; compare_score: number }[]; base: Coverage; compare: Coverage };
type MonthInfo = { key: string; label: string; scrobbles: number; partial: boolean };

const BASE_COLOR = "#ff7f50";
const CMP_COLOR = "#4aa3ff";
const BAR = 22;

const covText = (c: Coverage) => `재생 ${c.total_plays ? Math.round((c.covered_plays / c.total_plays) * 100) : 0}% 반영 · 아티스트 ${c.covered_artists} / ${c.total_artists}명`;

export function TagDistributionCard({
  distribution,
  query,
  baseLabel,
}: {
  distribution: TagDistribution;
  query: (extra?: Record<string, string | number>) => string;
  baseLabel: string;
}) {
  const [months, setMonths] = useState<MonthInfo[]>([]);
  const [month, setMonth] = useState("");
  const [cmp, setCmp] = useState<Compare | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${BASE_URL}/api/ai-prompt/periods?period=month`)
      .then((r) => r.json())
      .then((d) => !cancelled && setMonths((d.periods as MonthInfo[]) ?? []))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // 비교 월이나 기본 기간이 바뀌면 다시 받는다
  useEffect(() => {
    if (!month) {
      setCmp(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setError(null);
    fetch(`${BASE_URL}/api/taste/tag-compare${query({ month })}`)
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        if (d.error) setError(d.error);
        else setCmp(d as Compare);
      })
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [month, query]);

  const monthLabel = months.find((m) => m.key === month)?.label ?? month;
  const comparing = Boolean(month && cmp);

  return (
    <>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "0.8rem", flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>
          장르/태그 분포 {!comparing && <span style={{ fontSize: "0.8rem", color: "#888" }}>({covText(distribution)})</span>}
        </h2>
        <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.9rem" }}>
          <span style={{ color: MUTED }}>비교 월</span>
          <select
            value={month}
            onChange={(e) => setMonth(e.target.value)}
            aria-label="비교 월"
            style={{ padding: "0.3rem 0.5rem", borderRadius: 6, border: LINE, background: "transparent", color: "inherit" }}
          >
            <option value="">선택 안 함</option>
            {months.map((m) => (
              <option key={m.key} value={m.key}>
                {m.label} ({m.scrobbles.toLocaleString()}회){m.partial ? " · 일부" : ""}
              </option>
            ))}
          </select>
        </label>
      </div>
      {error && <p style={{ color: "#e07070" }}>{error}</p>}

      {comparing && cmp ? (
        <>
          <p style={{ color: MUTED, fontSize: "0.82rem", margin: "0.5rem 0", textAlign: "left" }}>
            막대는 각 기간의 전체 태그 점수에서 차지하는 비율(%)입니다. 재생 수가 다른 기간도 같은 축에서 비교할 수 있어요.
            <br />
            <span style={{ color: BASE_COLOR }}>■</span> 기준 {baseLabel} ({covText(cmp.base)}) · <span style={{ color: CMP_COLOR }}>■</span> 비교 {monthLabel} ({covText(cmp.compare)})
          </p>
          <ResponsiveContainer width="100%" height={Math.max(300, cmp.tags.length * 40 + 60)}>
            <BarChart data={cmp.tags} layout="vertical" barGap={-BAR} margin={{ right: 24 }}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis type="number" unit="%" />
              <YAxis dataKey="tag" type="category" width={150} interval={0} tick={{ fontSize: 13 }} />
              <Tooltip formatter={(v, name) => [`${v}%`, String(name)]} />
              <Legend />
              <Bar dataKey="base" name={`기준 · ${baseLabel}`} fill={BASE_COLOR} fillOpacity={0.55} stroke={BASE_COLOR} barSize={BAR} />
              <Bar dataKey="compare" name={`비교 · ${monthLabel}`} fill={CMP_COLOR} fillOpacity={0.55} stroke={CMP_COLOR} barSize={BAR} />
            </BarChart>
          </ResponsiveContainer>
        </>
      ) : (
        <ResponsiveContainer width="100%" height={Math.max(300, distribution.tags.length * 34 + 40)}>
          <BarChart data={distribution.tags} layout="vertical">
            <CartesianGrid strokeDasharray="3 3" />
            <XAxis type="number" />
            <YAxis dataKey="tag" type="category" width={150} interval={0} tick={{ fontSize: 13 }} />
            <Tooltip />
            <Bar dataKey="score" fill={BASE_COLOR} />
          </BarChart>
        </ResponsiveContainer>
      )}
    </>
  );
}
