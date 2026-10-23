import { useCallback, useEffect, useState, type CSSProperties } from "react";
import { AlbumYearEditor } from "./AlbumYearEditor";
import { BASE_URL } from "./config";
import { Num, Skeleton, stagger } from "./motion";
import { LINE } from "./RankRow";
import { CAT, MUTED, SCROBBLE_COLOR } from "./theme";

// Music by decade: 들은 앨범의 발매 연대별 분포. 연도는 MusicBrainz 우선 · Apple 보조 · config/album_years.txt 수동 보정으로 채운다.

type Top = { artist: string; album: string; year: number; plays: number };
type Decade = { decade: number; label: string; plays: number; albums: number; artists: number; top: Top[] };
type Decades = {
  error?: string;
  decades: Decade[];
  coverage: { known_plays: number; total_plays: number; pct: number; known_albums: number; total_albums: number; albums_unchecked: number; albums_not_found: number };
  reliable: boolean;
  oldest: { artist: string; album: string; year: number } | null;
  newest: { artist: string; album: string; year: number } | null;
  sources: Record<string, number>;
  ambiguous_albums: number;
  unknown_top: { artist: string; album: string; plays: number }[];
};
type FillResult = { error?: string; found: number; unknown: number; skipped: number; remaining: number; stopped: boolean };

type MetricKey = "plays" | "albums" | "artists";
const METRICS: { key: MetricKey; label: string; color: string; unit: string }[] = [
  { key: "plays", label: "스크로블", color: SCROBBLE_COLOR, unit: "회" },
  { key: "albums", label: CAT.album.label, color: CAT.album.main, unit: "개" },
  { key: "artists", label: CAT.artist.label, color: CAT.artist.main, unit: "명" },
];
const SOURCE_LABEL: Record<string, string> = { musicbrainz: "MusicBrainz", "musicbrainz:apple": "MusicBrainz+Apple", apple: "Apple", manual: "수동 보정" };

const pill = (on: boolean, color: string): CSSProperties => ({
  padding: "0.25rem 0.8rem",
  borderRadius: 999,
  border: on ? `1px solid ${color}` : LINE,
  background: on ? color : "transparent",
  color: on ? "#1a1b1e" : "inherit",
  fontWeight: on ? 700 : 500,
  fontSize: "0.85rem",
  cursor: "pointer",
});

export function DecadeCard({ query }: { query: (extra?: Record<string, string | number>) => string }) {
  const [data, setData] = useState<Decades | null>(null);
  const [metric, setMetric] = useState<MetricKey>("plays");
  const [open, setOpen] = useState<number | null>(null);
  const [filling, setFilling] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetch(`${BASE_URL}/api/overview/decades${query()}`)
      .then((r) => r.json())
      .then((d) => !cancelled && setData(d.error ? null : (d as Decades)))
      .catch(() => !cancelled && setData(null));
    return () => {
      cancelled = true;
    };
  }, [query, version]);

  const fill = useCallback(() => {
    setFilling(true);
    setMessage(null);
    fetch(`${BASE_URL}/api/album-years/fill`, { method: "POST" })
      .then((r) => r.json())
      .then((d: FillResult) => {
        if (d.error) {
          setMessage(`에러: ${d.error}`);
          return;
        }
        const parts = [`${d.found}개 찾음`];
        if (d.unknown) parts.push(`${d.unknown}개는 못 찾음`);
        if (d.skipped) parts.push(`${d.skipped}개는 오류로 보류`);
        if (d.remaining) parts.push(`남은 ${d.remaining}개`);
        setMessage(parts.join(" · ") + (d.stopped ? " — MusicBrainz 에 연달아 닿지 않아 멈췄어요. 잠시 뒤에 다시 눌러 주세요." : ""));
        setVersion((v) => v + 1);
      })
      .catch((e) => setMessage(`에러: ${e.message}`))
      .finally(() => setFilling(false));
  }, []);

  if (!data) return <Skeleton lines={4} height={26} style={{ margin: "1rem 0" }} />;
  const cov = data.coverage;
  if (cov.total_albums === 0) return null;

  const m = METRICS.find((x) => x.key === metric)!;
  const max = Math.max(...data.decades.map((d) => d[metric]), 1);
  const pct = Math.round(cov.pct * 100);
  const sources = Object.entries(data.sources).map(([k, v]) => `${SOURCE_LABEL[k] ?? k} ${v}`).join(" · ");

  // 비어 있는 연대가 셋 이상 이어지면 한 줄로 접는다 (잘못 들어간 아주 오래된 연도 하나가 막대 축을 늘이지 않게)
  type Row = { gap: false; d: Decade } | { gap: true; label: string };
  const rows: Row[] = [];
  for (let i = 0; i < data.decades.length; ) {
    let j = i;
    while (j < data.decades.length && data.decades[j].plays === 0) j++;
    if (j - i >= 3) {
      rows.push({ gap: true, label: `${data.decades[i].label}–${data.decades[j - 1].label}` });
      i = j;
    } else {
      rows.push({ gap: false, d: data.decades[i] });
      i++;
    }
  }

  return (
    <section style={{ margin: "1.6rem 0 0.4rem", textAlign: "left" }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem", flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>연대별 음악 <span style={{ color: MUTED, fontSize: "0.9rem", fontWeight: 500 }}>Music by decade</span></h2>
        <div style={{ display: "flex", gap: "0.4rem" }}>
          {METRICS.map((x) => (
            <button key={x.key} type="button" onClick={() => setMetric(x.key)} style={pill(metric === x.key, x.color)}>{x.label}</button>
          ))}
        </div>
      </div>

      {data.decades.length > 0 ? (
        <div style={{ margin: "0.8rem 0 0.4rem" }}>
          {rows.map((row, i) => {
            if (row.gap) {
              return (
                <div key={row.label} style={{ padding: "0.35rem 0.25rem", borderBottom: LINE, color: MUTED, fontSize: "0.85rem" }}>
                  ⋯ {row.label} 들은 앨범 없음
                </div>
              );
            }
            const d = row.d;
            const v = d[metric];
            const isOpen = open === d.decade;
            return (
              <div key={d.decade} className="aym-rise" style={{ ...stagger(i, 40), borderBottom: LINE }}>
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => setOpen(isOpen ? null : d.decade)}
                  onKeyDown={(e) => e.key === "Enter" && setOpen(isOpen ? null : d.decade)}
                  style={{ display: "flex", alignItems: "center", gap: "0.9rem", padding: "0.5rem 0.25rem", cursor: v ? "pointer" : "default" }}
                >
                  <span style={{ width: 56, fontWeight: 700, flexShrink: 0 }}>{d.label}</span>
                  <div style={{ flex: 1, minWidth: 0, height: 26, background: "rgba(128,128,128,0.12)", borderRadius: 4, overflow: "hidden" }}>
                    {v > 0 && <div key={metric} className="aym-bar" style={{ width: `${(v / max) * 100}%`, height: "100%", background: m.color, borderRadius: 4 }} />}
                  </div>
                  <span style={{ width: 84, textAlign: "right", flexShrink: 0, fontWeight: 600 }}>
                    <Num value={v} />
                    <span style={{ color: MUTED, fontWeight: 400, fontSize: "0.85rem" }}>{m.unit}</span>
                  </span>
                </div>
                {isOpen && d.top.length > 0 && (
                  <ol style={{ margin: "0 0 0.6rem 4.2rem", paddingLeft: "1.1rem", color: MUTED, fontSize: "0.88rem" }}>
                    {d.top.map((t) => (
                      <li key={`${t.artist}-${t.album}`}>
                        <span style={{ color: "CanvasText" }}>{t.album}</span> — {t.artist} ({t.year}) · {t.plays.toLocaleString()}회
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            );
          })}
        </div>
      ) : (
        <p style={{ color: MUTED }}>아직 발매연도를 아는 앨범이 없어요. 아래 버튼으로 연도를 채워 보세요.</p>
      )}

      <p style={{ color: MUTED, fontSize: "0.82rem", margin: "0.4rem 0" }}>
        스크로블 기준 <strong style={{ color: "CanvasText" }}>{pct}%</strong> 반영 (앨범 {cov.known_albums.toLocaleString()} / {cov.total_albums.toLocaleString()}개)
        {sources ? ` · 출처: ${sources}` : ""}
        {data.ambiguous_albums ? ` · 같은 제목의 다른 음반이 있어 확실하지 않은 앨범 ${data.ambiguous_albums}개` : ""}
      </p>
      {!data.reliable && data.decades.length > 0 && (
        <p style={{ color: "#e0a030", fontSize: "0.85rem", margin: "0.2rem 0" }}>
          연도를 아는 비율이 낮아서 실제 분포와 다를 수 있어요. 연도를 더 채우면 정확해집니다.
        </p>
      )}
      {data.oldest && data.newest && (
        <p style={{ color: MUTED, fontSize: "0.82rem", margin: "0.2rem 0" }}>
          가장 오래된 앨범: {data.oldest.album} — {data.oldest.artist} ({data.oldest.year}) · 가장 최근: {data.newest.album} — {data.newest.artist} ({data.newest.year})
        </p>
      )}

      <div style={{ display: "flex", alignItems: "center", gap: "0.8rem", flexWrap: "wrap", margin: "0.5rem 0" }}>
        {cov.albums_unchecked > 0 && (
          <button type="button" onClick={fill} disabled={filling} style={{ ...pill(false, CAT.album.main), opacity: filling ? 0.6 : 1 }}>
            {filling ? "조회 중… (최대 1분)" : `🔎 연도 더 채우기 (아직 조회 전 ${cov.albums_unchecked.toLocaleString()}개 중 재생 많은 순 25개)`}
          </button>
        )}
        {message && <span style={{ color: MUTED, fontSize: "0.85rem" }}>{message}</span>}
      </div>

      <div style={{ margin: "0.4rem 0" }}>
        <button type="button" onClick={() => setEditing((e) => !e)} style={pill(editing, CAT.artist.main)}>
          ✏️ 연도 직접 입력·수정{cov.total_albums > cov.known_albums ? ` (연도 모르는 앨범 ${(cov.total_albums - cov.known_albums).toLocaleString()}개)` : ""}
        </button>
      </div>
      {editing && <AlbumYearEditor onChanged={() => setVersion((v) => v + 1)} />}
    </section>
  );
}
