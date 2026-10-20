import { useEffect, useState } from "react";
import { BASE_URL } from "./config";
import { Cover } from "./Cover";
import { agoText } from "./format";
import { Skeleton, stagger } from "./motion";
import { CAT, type Cat } from "./theme";
import type { LibraryTarget } from "./Library";

// "최근 발견한 곡/아티스트/앨범": 처음 들은 순 목록. 순위 목록(RankRow)과 같은 줄 모양(커버 · 이름 · 부제 · 오른쪽 수치)이고,
// 누르면 Library 의 상세 페이지로 이동한다.

type Item = { name: string; artist: string | null; album?: string | null; first_listened: string };

const LINE = "1px solid rgba(128,128,128,0.25)";

export function DiscoveryList({ cat, query, onOpen }: { cat: Cat; query: (extra?: Record<string, string | number>) => string; onOpen: (t: LibraryTarget) => void }) {
  const [items, setItems] = useState<Item[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setItems(null);
    setError(null);
    fetch(`${BASE_URL}/api/discovery/timeline${query({ category: cat, limit: 30 })}`)
      .then((r) => r.json())
      .then((d) => {
        if (cancelled) return;
        if (d.error) setError(d.error);
        else setItems(d.results as Item[]);
      })
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [cat, query]);

  if (error) return <p style={{ color: "#d66" }}>{error}</p>;
  if (!items) return <Skeleton lines={6} height={44} />;
  if (items.length === 0) return <p style={{ color: "#999" }}>이 기간에 새로 발견한 항목이 없어요.</p>;

  const target = (it: Item): LibraryTarget =>
    cat === "artist" ? { kind: "artist", name: it.name } : cat === "album" ? { kind: "album", name: it.name, artist: it.artist } : { kind: "track", name: it.name, artist: it.artist, album: null };

  return (
    <div style={{ textAlign: "left" }}>
      {items.map((it, idx) => {
        const date = it.first_listened.slice(0, 10);
        const time = it.first_listened.slice(11);
        const open = () => onOpen(target(it));
        return (
          <div
            key={`${it.artist}|${it.name}|${it.first_listened}`}
            className="aym-rise"
            role="button"
            tabIndex={0}
            onClick={open}
            onKeyDown={(e) => e.key === "Enter" && open()}
            style={{ display: "flex", alignItems: "center", gap: "0.9rem", padding: "0.6rem 0.25rem", borderBottom: LINE, cursor: "pointer", ...stagger(idx) }}
          >
            {cat === "artist" ? <Cover kind="artist" artist={it.name} size={44} /> : <Cover kind="album" artist={it.artist} album={cat === "album" ? it.name : it.album} size={44} />}
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.name}</div>
              {cat !== "artist" && it.artist && <div style={{ color: "#999", fontSize: "0.9rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{it.artist}</div>}
            </div>
            <div style={{ textAlign: "right", flexShrink: 0 }}>
              <span style={{ display: "inline-block", background: CAT[cat].main, color: "#1a1b1e", fontWeight: 700, fontSize: "0.8rem", padding: "0.1rem 0.55rem", borderRadius: 3 }}>
                {agoText(date)}
              </span>
              <div style={{ color: "#999", fontSize: "0.8rem", marginTop: 2 }}>
                {date} {time}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
