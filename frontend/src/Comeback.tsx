import { useEffect, useMemo, useState } from "react";
import { BASE_URL } from "./config";
import { Sparkline, type TopItem } from "./Consistency";
import { Cover } from "./Cover";
import type { LibraryTarget } from "./Library";
import { Skeleton, stagger } from "./motion";
import { CAT, type Cat } from "./theme";

// 다시 들을 만한 것: 한때 꾸준히 들었는데 한동안 안 들은 아티스트·앨범·곡.
// 규칙(전체 기간 기준, 재생 많은 상위 POOL 개 안에서): 총 MIN_PLAYS번 이상 · 서로 다른 MIN_ACTIVE개월 이상 들었고 · 마지막으로 들은 지 MIN_GAP개월 이상.
// AI 없이 월별 재생 기록(서버의 consistency)만으로 계산한다.

const POOL = 120;
const MIN_PLAYS = 10;
const MIN_ACTIVE = 3;
const MIN_GAP = 3;
const PAGE = 6;

type Sort = "plays" | "gap";
const NOUN: Record<Cat, { word: string; unit: string }> = { artist: { word: "아티스트", unit: "명" }, album: { word: "앨범", unit: "개" }, track: { word: "곡", unit: "곡" } };
const ym = (m: string) => m.replace("-", ".");

export function ComebackList({ cat, onOpen }: { cat: Cat; onOpen: (t: LibraryTarget) => void }) {
  const [items, setItems] = useState<TopItem[] | null>(null);
  const [months, setMonths] = useState<string[]>([]);
  const [sort, setSort] = useState<Sort>("plays");
  const [shown, setShown] = useState(PAGE);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    setShown(PAGE);
    setError(null);
    fetch(`${BASE_URL}/api/music/top?category=${cat}&limit=${POOL}&metric=plays`)
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        if (d.error) setError(d.error);
        else {
          setItems(d.results as TopItem[]);
          setMonths((d.months as string[]) ?? []);
        }
      })
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [cat]);

  const list = useMemo(() => {
    const c = (items ?? []).filter((it) => it.consistency && it.count >= MIN_PLAYS && it.consistency.active_months >= MIN_ACTIVE && it.consistency.months_since_last >= MIN_GAP);
    return c.sort((a, b) => (sort === "gap" ? b.consistency!.months_since_last - a.consistency!.months_since_last || b.count - a.count : b.count - a.count));
  }, [items, sort]);

  const color = CAT[cat].main;
  const { word, unit } = NOUN[cat];
  const target = (it: TopItem): LibraryTarget =>
    cat === "artist" ? { kind: "artist", name: it.name } : cat === "album" ? { kind: "album", name: it.name, artist: it.artist } : { kind: "track", name: it.name, artist: it.artist, album: null };

  if (error) return <p style={{ color: "#e07070" }}>{error}</p>;
  if (!items) return <Skeleton lines={3} height={64} />;

  const longest = list.length ? list.reduce((a, b) => (b.consistency!.months_since_last > a.consistency!.months_since_last ? b : a)) : null;

  return (
    <>
      <div className="aym-h3">
        <h3>다시 들을 만한 {word}</h3>
        <span>전체 기간 기준 · 총 {MIN_PLAYS}번 이상, {MIN_ACTIVE}개월 이상 들었는데 {MIN_GAP}개월 넘게 안 들은 {word}</span>
      </div>
      {list.length === 0 ? (
        <p className="aym-lede xs">지금은 {MIN_GAP}개월 넘게 쉬고 있는 단골 {word}이 없어요.</p>
      ) : (
        <>
          <p className="aym-lede xs">
            한때 꾸준히 듣다가 {MIN_GAP}개월 넘게 안 들은 {word}이 <b className="num">{list.length.toLocaleString()}{unit}</b> 있어요. 가장 오래 쉰 건 <b>{longest!.name}</b>(<b className="num">{longest!.consistency!.months_since_last}개월</b>)이에요.
          </p>
          <div className="aym-seg sm" role="group" aria-label="정렬" style={{ margin: "14px 0 12px" }}>
            <button aria-pressed={sort === "plays"} onClick={() => setSort("plays")}>많이 들은 순</button>
            <button aria-pressed={sort === "gap"} onClick={() => setSort("gap")}>오래 쉰 순</button>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(290px, 1fr))", gap: 12 }}>
            {list.slice(0, shown).map((it, i) => {
              const c = it.consistency!;
              const open = () => onOpen(target(it));
              return (
                <div
                  key={`${it.artist}|${it.name}`}
                  className="aym-panel aym-rise"
                  role="button"
                  tabIndex={0}
                  onClick={open}
                  onKeyDown={(e) => e.key === "Enter" && open()}
                  style={{ ...stagger(i % PAGE, 50), cursor: "pointer", padding: "14px 16px", display: "flex", gap: 14, alignItems: "flex-start" }}
                >
                  {cat === "artist" ? <Cover kind="artist" artist={it.name} size={56} /> : <Cover kind="album" artist={it.artist} album={cat === "album" ? it.name : it.album} size={56} />}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.name}</div>
                    {cat !== "artist" && it.artist && <div style={{ color: "var(--text-3)", fontSize: "0.82rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.artist}</div>}
                    <div style={{ display: "flex", alignItems: "center", gap: 8, margin: "7px 0 6px", flexWrap: "wrap" }}>
                      <span style={{ background: color, color: "#1a1b1e", fontWeight: 800, fontSize: "0.75rem", padding: "2px 9px", borderRadius: 999 }}>{c.months_since_last}개월째 쉬는 중</span>
                      <span className="num" style={{ fontSize: "0.85rem", fontWeight: 700 }}>총 {it.count.toLocaleString()}번</span>
                    </div>
                    <Sparkline monthly={c.monthly} months={months} width={150} height={22} color={color} />
                    <div style={{ color: "var(--text-3)", fontSize: "0.75rem", marginTop: 4 }}>마지막 {ym(c.last_month)} · 가장 많이 들은 달 {ym(c.peak_month)}</div>
                  </div>
                </div>
              );
            })}
          </div>
          {shown < list.length && (
            <div style={{ marginTop: 14 }}>
              <button onClick={() => setShown((n) => n + PAGE)}>더 보기 ({shown}/{list.length})</button>
            </div>
          )}
        </>
      )}
    </>
  );
}
