import { useEffect, useState } from "react";
import { BASE_URL } from "./config";
import { Cover } from "./Cover";
import { dominantColor } from "./coverColor";
import type { LibraryTarget, SortMode } from "./Library";
import { Num, Reveal, Skeleton, stagger } from "./motion";
import { cover } from "./Share";
import { CAT, type Cat } from "./theme";

// 요약 구역의 "가장 많이 들은": 아티스트·앨범·트랙마다 카드 하나.
// 1위 커버의 대표색이 카드 배경으로 번지고(리플레이식), 순위·재생 수·전체 대비 %·1위 대비 막대로 수치를 명시한다.

type Item = { name: string; artist: string | null; album?: string | null; count: number };

const KIND: { cat: Cat; title: string }[] = [
  { cat: "artist", title: "아티스트" },
  { cat: "album", title: "앨범" },
  { cat: "track", title: "트랙" },
];

const pct = (n: number, total: number) => (total > 0 ? Math.round((n / total) * 1000) / 10 : 0);

function toTarget(cat: Cat, it: Item): LibraryTarget {
  if (cat === "artist") return { kind: "artist", name: it.name };
  if (cat === "album") return { kind: "album", name: it.name, artist: it.artist };
  return { kind: "track", name: it.name, artist: it.artist, album: null };
}

function TopCard({ cat, title, items, total, onOpen, onMore, index }: { cat: Cat; title: string; items: Item[]; total: number; onOpen: (t: LibraryTarget) => void; onMore: (c: Cat, s: SortMode) => void; index: number }) {
  const [tint, setTint] = useState<string | null>(null);
  const first = items[0];

  // 1위 커버에서 대표색을 뽑는다 (못 뽑으면 카테고리 색)
  useEffect(() => {
    setTint(null);
    if (!first) return;
    let cancelled = false;
    (cat === "artist" ? cover("artist", first.name) : cover("album", first.artist, cat === "album" ? first.name : first.album)).then((img) => {
      if (!cancelled && img) setTint(dominantColor(img));
    });
    return () => {
      cancelled = true;
    };
  }, [cat, first?.name, first?.artist, first?.album]);

  if (!first) return null;
  const base = tint ?? CAT[cat].main;
  const max = first.count;
  // 트랙은 그 곡이 들어 있는 앨범의 커버로 보여 준다
  const heroCover =
    cat === "artist" ? (
      <Cover kind="artist" artist={first.name} size={112} />
    ) : (
      <Cover kind="album" artist={first.artist} album={cat === "album" ? first.name : first.album} size={112} />
    );

  return (
    <div
      className="aym-rise"
      style={{
        ...stagger(index, 90),
        position: "relative",
        overflow: "hidden",
        borderRadius: 26,
        padding: 20,
        border: "1px solid rgba(255,255,255,0.1)",
        background: `linear-gradient(165deg, color-mix(in srgb, ${base} 40%, #0e0e10) 0%, color-mix(in srgb, ${base} 14%, #0e0e10) 62%, #0e0e10 100%)`,
        transition: "background 600ms",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ display: "inline-block", fontSize: "0.78rem", fontWeight: 700, padding: "3px 11px", borderRadius: 999, background: "rgba(0,0,0,0.32)" }}>{title}</span>
        <button onClick={() => onMore(cat, "plays")} style={{ background: "transparent", padding: "0.2rem 0.5rem", fontSize: "0.8rem", color: "rgba(255,255,255,0.7)" }}>
          전체 보기 ›
        </button>
      </div>

      <div
        role="button"
        tabIndex={0}
        onClick={() => onOpen(toTarget(cat, first))}
        onKeyDown={(e) => e.key === "Enter" && onOpen(toTarget(cat, first))}
        style={{ display: "flex", gap: 14, alignItems: "flex-end", margin: "16px 0 4px", cursor: "pointer" }}
      >
        <div style={{ borderRadius: cat === "artist" ? "50%" : 14, overflow: "hidden", flexShrink: 0, boxShadow: "0 14px 30px rgba(0,0,0,0.45)", display: "flex" }}>{heroCover}</div>
        <div style={{ minWidth: 0 }}>
          <h4 style={{ fontSize: "1.3rem", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1.2, overflowWrap: "anywhere" }}>{first.name}</h4>
          {cat !== "artist" && first.artist && <p style={{ fontSize: "0.85rem", color: "rgba(255,255,255,0.72)", marginTop: 2 }}>{first.artist}</p>}
          {cat === "artist" && <p style={{ fontSize: "0.85rem", color: "rgba(255,255,255,0.72)", marginTop: 2 }}>1위</p>}
        </div>
      </div>

      <div className="num" style={{ fontSize: "2.8rem", fontWeight: 800, letterSpacing: "-0.03em", lineHeight: 1, marginTop: 14, display: "flex", alignItems: "baseline", gap: 6, flexWrap: "wrap" }}>
        <Num value={first.count} />
        <small style={{ fontFamily: "var(--font)", fontSize: "0.9rem", fontWeight: 600, color: "rgba(255,255,255,0.65)", letterSpacing: 0 }}>번</small>
        <span style={{ fontFamily: "var(--font)", fontSize: "0.78rem", fontWeight: 700, padding: "2px 9px", borderRadius: 999, background: "rgba(255,255,255,0.16)", letterSpacing: 0 }} title="전체 스크로블에서 차지하는 비율">
          {pct(first.count, total)}%
        </span>
      </div>

      <ol style={{ listStyle: "none", padding: 0, margin: "14px 0 0", borderTop: "1px solid rgba(255,255,255,0.14)" }}>
        {items.slice(1).map((it, i) => (
          <li
            key={`${it.artist}|${it.name}`}
            role="button"
            tabIndex={0}
            onClick={() => onOpen(toTarget(cat, it))}
            onKeyDown={(e) => e.key === "Enter" && onOpen(toTarget(cat, it))}
            style={{ padding: "9px 0", borderBottom: "1px solid rgba(255,255,255,0.08)", fontSize: "0.9rem", cursor: "pointer" }}
          >
            <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
              <b className="num" style={{ width: 14, color: "rgba(255,255,255,0.5)" }}>{i + 2}</b>
              <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.name}</span>
              <span className="num" style={{ fontWeight: 700 }}>{it.count.toLocaleString()}</span>
              <em style={{ fontStyle: "normal", fontSize: "0.75rem", color: "rgba(255,255,255,0.5)", minWidth: 38, textAlign: "right" }}>{pct(it.count, total)}%</em>
            </div>
            <div style={{ height: 3, borderRadius: 2, background: "rgba(255,255,255,0.12)", margin: "6px 0 0 24px" }}>
              <div className="aym-bar" style={{ width: `${Math.max(4, (it.count / max) * 100)}%`, height: "100%", borderRadius: 2, background: CAT[cat].main, animationDelay: `${200 + i * 70}ms` }} />
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}

export function TopCards({ query, total, onOpen, onMore }: { query: (extra?: Record<string, string | number>) => string; total: number; onOpen: (t: LibraryTarget) => void; onMore: (c: Cat, s: SortMode) => void }) {
  const [data, setData] = useState<Record<Cat, Item[]> | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all(
      KIND.map((k) =>
        fetch(`${BASE_URL}/api/music/top${query({ category: k.cat, limit: 5, metric: "plays" })}`)
          .then((r) => r.json())
          .then((d) => (Array.isArray(d.results) ? (d.results as Item[]) : []))
          .catch(() => [] as Item[])
      )
    ).then(([artist, album, track]) => !cancelled && setData({ artist, album, track }));
    return () => {
      cancelled = true;
    };
  }, [query]);

  return (
    <>
      <div className="aym-h3">
        <h3>가장 많이 들은</h3>
        <span>숫자 옆 %는 전체 스크로블에서 차지하는 비율이에요</span>
      </div>
      {!data ? (
        <Skeleton lines={3} height={120} />
      ) : (
        <Reveal minHeight={420}>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(300px, 1fr))", gap: 14 }}>
            {KIND.map((k, i) => (
              <TopCard key={k.cat} cat={k.cat} title={k.title} items={data[k.cat]} total={total} onOpen={onOpen} onMore={onMore} index={i} />
            ))}
          </div>
        </Reveal>
      )}
    </>
  );
}
