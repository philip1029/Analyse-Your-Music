import { useEffect, useRef, useState } from "react";
import { BASE_URL } from "./config";
import { Cover } from "./Cover";
import type { LibraryTarget } from "./Library";
import { CAT } from "./theme";

// 아티스트·앨범·곡 이름 검색: 입력하면 종류별 결과가 드롭다운으로 나오고, 고르면 Music 탭의 상세 페이지로 이동한다.

type Hit = { name: string; artist: string | null; album?: string | null; count: number };
type Result = { artists: Hit[]; albums: Hit[]; tracks: Hit[] };
type Flat = { kind: "artist" | "album" | "track"; hit: Hit };

const GROUPS: { key: keyof Result; kind: Flat["kind"]; title: string }[] = [
  { key: "artists", kind: "artist", title: "Artists" },
  { key: "albums", kind: "album", title: "Albums" },
  { key: "tracks", kind: "track", title: "Tracks" },
];

export function SearchBox({ query, rangeLabel, onPick }: { query: (extra?: Record<string, string | number>) => string; rangeLabel: string; onPick: (t: LibraryTarget) => void }) {
  const [text, setText] = useState("");
  const [result, setResult] = useState<Result | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const box = useRef<HTMLDivElement>(null);

  // 입력이 멈추면(0.25초) 검색한다. 늦게 도착한 옛 응답은 버린다.
  useEffect(() => {
    const q = text.trim();
    if (!q) {
      setResult(null);
      setLoading(false);
      return;
    }
    const ctrl = new AbortController();
    setLoading(true);
    const timer = setTimeout(() => {
      fetch(`${BASE_URL}/api/search${query({ q, limit: 5 })}`, { signal: ctrl.signal })
        .then((r) => r.json())
        .then((d) => {
          if (d.error) return setResult(null);
          setResult(d as Result);
          setActive(0);
        })
        .catch(() => {})
        .finally(() => !ctrl.signal.aborted && setLoading(false));
    }, 250);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [text, query]);

  // 바깥을 누르면 닫는다
  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const flat: Flat[] = result ? GROUPS.flatMap((g) => result[g.key].map((hit) => ({ kind: g.kind, hit }))) : [];

  const pick = (f: Flat) => {
    onPick(f.kind === "artist" ? { kind: "artist", name: f.hit.name } : f.kind === "album" ? { kind: "album", name: f.hit.name, artist: f.hit.artist } : { kind: "track", name: f.hit.name, artist: f.hit.artist, album: null });
    setOpen(false);
    setText("");
  };

  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") setOpen(false);
    else if (e.key === "ArrowDown" && flat.length) {
      e.preventDefault();
      setActive((a) => (a + 1) % flat.length);
    } else if (e.key === "ArrowUp" && flat.length) {
      e.preventDefault();
      setActive((a) => (a - 1 + flat.length) % flat.length);
    } else if (e.key === "Enter" && flat[active]) pick(flat[active]);
  };

  let index = -1;
  return (
    <div ref={box} style={{ position: "relative", flex: "1 1 220px", maxWidth: 420, marginLeft: "auto" }}>
      <input
        type="search"
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKey}
        placeholder="🔍 아티스트 · 앨범 · 곡 검색"
        aria-label="검색"
        style={{ width: "100%", boxSizing: "border-box", padding: "0.5rem 0.8rem", borderRadius: 8 }}
      />
      {open && text.trim() && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            left: 0,
            right: 0,
            zIndex: 30,
            maxHeight: "70vh",
            overflowY: "auto",
            textAlign: "left",
            background: "Canvas",
            color: "CanvasText",
            border: "1px solid rgba(128,128,128,0.4)",
            borderRadius: 10,
            boxShadow: "0 8px 24px rgba(0,0,0,0.35)",
            padding: "0.3rem 0",
          }}
        >
          {loading && !result && <div style={{ padding: "0.7rem 1rem", color: "#999" }}>검색 중...</div>}
          {result && flat.length === 0 && !loading && <div style={{ padding: "0.7rem 1rem", color: "#999" }}>“{text.trim()}” 결과가 없어요 ({rangeLabel} 기준)</div>}
          {result &&
            GROUPS.map((g) =>
              result[g.key].length === 0 ? null : (
                <div key={g.key}>
                  <div style={{ padding: "0.4rem 1rem 0.2rem", fontSize: "0.72rem", fontWeight: 700, letterSpacing: "0.03em", color: CAT[g.kind].main, textTransform: "uppercase" }}>{g.title}</div>
                  {result[g.key].map((hit) => {
                    index += 1;
                    const i = index;
                    return (
                      <div
                        key={`${g.key}|${hit.artist}|${hit.name}`}
                        role="option"
                        aria-selected={i === active}
                        onMouseEnter={() => setActive(i)}
                        onClick={() => pick({ kind: g.kind, hit })}
                        style={{ display: "flex", alignItems: "center", gap: "0.7rem", padding: "0.4rem 1rem", cursor: "pointer", background: i === active ? "rgba(128,128,128,0.2)" : "transparent" }}
                      >
                        {g.kind === "artist" ? <Cover kind="artist" artist={hit.name} size={32} /> : <Cover kind="album" artist={hit.artist} album={g.kind === "album" ? hit.name : hit.album} size={32} />}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <div style={{ fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{hit.name}</div>
                          {g.kind !== "artist" && hit.artist && <div style={{ color: "#999", fontSize: "0.8rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{hit.artist}</div>}
                        </div>
                        <span style={{ color: "#999", fontSize: "0.8rem", flexShrink: 0 }}>{hit.count.toLocaleString()}회</span>
                      </div>
                    );
                  })}
                </div>
              )
            )}
        </div>
      )}
    </div>
  );
}
