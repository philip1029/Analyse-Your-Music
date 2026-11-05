import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { BASE_URL } from "./config";
import { RankRow, LINE } from "./RankRow";
import { Skeleton } from "./motion";

// 좋아요(♥) 곡: 곡 목록 어디서나 하트를 누르면 data/favorites.json 에 저장되고, Music 탭의 "♥ 좋아요" 에서 모아 본다.
// 곡은 이름(대소문자·띄어쓰기·기호 무시)과 아티스트로 알아본다 — 서버의 name_key 와 같은 규칙이다.

export type Favorite = {
  name: string;
  artist: string | null;
  artists: string[];            // 이 곡의 기록에 쓰인 모든 아티스트 표기
  album: string | null;
  duration: number | null;
  added: string;
  found: boolean;
  scrobbles: number;
  first_played: string | null;
  last_played: string | null;
};

const nameKey = (s: string) => s.normalize("NFKC").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, "") || s.toLowerCase();

type Ctx = {
  items: Favorite[] | null;
  error: string | null;
  isFav: (artist: string | null, name: string) => boolean;
  toggle: (artist: string | null, name: string) => void;
};

const FavoritesContext = createContext<Ctx | null>(null);

export function FavoritesProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Favorite[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  // 처음 열 때와 탭으로 돌아올 때마다 다시 읽는다 (가져오기 스크립트나 다른 창에서 바뀐 목록이 새로고침 없이 반영된다)
  useEffect(() => {
    const load = () =>
      fetch(`${BASE_URL}/api/favorites`)
        .then((r) => r.json())
        .then((d) => (d.error ? setError(d.error) : setItems(d.items as Favorite[])))
        .catch((e) => setError(e.message));
    const onVisible = () => document.visibilityState === "visible" && load();
    load();
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("focus", load);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("focus", load);
    };
  }, []);

  const index = useMemo(() => {
    const m = new Map<string, Favorite[]>();
    for (const f of items ?? []) m.set(nameKey(f.name), [...(m.get(nameKey(f.name)) ?? []), f]);
    return m;
  }, [items]);

  const find = useCallback(
    (artist: string | null, name: string) => (index.get(nameKey(name)) ?? []).find((f) => (artist ? f.artists.includes(artist) || f.artist === artist : !f.artist)),
    [index]
  );

  const toggle = useCallback(
    (artist: string | null, name: string) => {
      const current = find(artist, name);
      const favorite = !current;
      // 서버 응답을 기다리지 않고 바로 하트를 바꾼다 (실패하면 서버가 돌려준 목록으로 되돌아간다)
      setItems((prev) =>
        favorite
          ? [{ name, artist, artists: artist ? [artist] : [], album: null, duration: null, added: new Date().toISOString().slice(0, 10), found: false, scrobbles: 0, first_played: null, last_played: null }, ...(prev ?? [])]
          : (prev ?? []).filter((f) => f !== current)
      );
      fetch(`${BASE_URL}/api/favorites`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ artist, track: current?.name ?? name, favorite }) })
        .then((r) => r.json())
        .then((d) => (d.error ? setError(d.error) : setItems(d.items as Favorite[])))
        .catch((e) => setError(e.message));
    },
    [find]
  );

  const value = useMemo<Ctx>(() => ({ items, error, isFav: (a, n) => !!find(a, n), toggle }), [items, error, find, toggle]);
  return <FavoritesContext.Provider value={value}>{children}</FavoritesContext.Provider>;
}

export const useFavorites = () => useContext(FavoritesContext);

export function HeartButton({ artist, name, size = 20 }: { artist: string | null; name: string; size?: number }) {
  const fav = useFavorites();
  if (!fav || fav.items === null) return null;
  const on = fav.isFav(artist, name);
  return (
    <button
      aria-pressed={on}
      aria-label={on ? "좋아요 취소" : "좋아요"}
      title={on ? "좋아요 취소" : "좋아요"}
      onClick={(e) => {
        e.stopPropagation();
        fav.toggle(artist, name);
      }}
      onKeyDown={(e) => e.stopPropagation()}
      style={{ background: "none", border: "none", padding: "0 0.25rem", cursor: "pointer", fontSize: size, lineHeight: 1, flexShrink: 0, color: on ? "#e0556b" : "#999", opacity: on ? 1 : 0.7 }}
    >
      {on ? "♥" : "♡"}
    </button>
  );
}

type Sort = "added" | "plays" | "first";
const SORTS: { id: Sort; label: string }[] = [
  { id: "added", label: "최근 좋아요 순" },
  { id: "plays", label: "재생 수 순" },
  { id: "first", label: "처음 들은 순" },
];

export function FavoritesView({ onOpen }: { onOpen: (f: Favorite) => void }) {
  const fav = useFavorites();
  const [sort, setSort] = useState<Sort>("added");
  const [year, setYear] = useState<string | null>(null);        // 처음 들은 해로 거르기
  const items = fav?.items ?? null;

  const years = useMemo(() => [...new Set((items ?? []).filter((f) => f.first_played).map((f) => (f.first_played as string).slice(0, 4)))].sort().reverse(), [items]);
  const shown = useMemo(() => {
    const list = (items ?? []).filter((f) => f.found && (!year || f.first_played?.startsWith(year)));
    const by: Record<Sort, (a: Favorite, b: Favorite) => number> = {
      added: (a, b) => b.added.localeCompare(a.added),
      plays: (a, b) => b.scrobbles - a.scrobbles,
      first: (a, b) => (b.first_played ?? "").localeCompare(a.first_played ?? ""),
    };
    return [...list].sort(by[sort]);                          // 정렬이 안정적이라 같은 값은 저장된 순서를 지킨다
  }, [items, sort, year]);
  const missing = (items ?? []).filter((f) => !f.found);

  if (fav?.error && !items) return <p style={{ color: "#d66" }}>{fav.error}</p>;
  if (!items) return <Skeleton lines={5} height={44} />;
  if (items.length === 0) return <p style={{ color: "#999" }}>아직 좋아요한 곡이 없어요. 곡 목록의 ♡ 를 눌러 보세요.</p>;

  const max = Math.max(1, ...shown.map((f) => f.scrobbles));
  const chip = (active: boolean) => ({ padding: "0.25rem 0.7rem", fontSize: "0.85rem", fontWeight: active ? 700 : 400, border: active ? "2px solid #e0556b" : "1px solid #666" });
  return (
    <>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap", marginBottom: "0.6rem" }}>
        {SORTS.map((o) => (
          <button key={o.id} onClick={() => setSort(o.id)} style={chip(sort === o.id)}>
            {o.label}
          </button>
        ))}
      </div>
      {years.length > 1 && (
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap", marginBottom: "0.8rem" }}>
          <span style={{ color: "#999", fontSize: "0.85rem" }}>처음 들은 해</span>
          <button onClick={() => setYear(null)} style={chip(year === null)}>
            전체
          </button>
          {years.map((y) => (
            <button key={y} onClick={() => setYear(y)} style={chip(year === y)}>
              {y}
            </button>
          ))}
        </div>
      )}
      <p style={{ color: "#999", fontSize: "0.85rem", margin: "0 0 0.4rem" }}>
        ♥ {shown.length}곡{year ? ` (${year}년에 처음 들은 곡)` : ""} · 재생 수와 처음 들은 날은 전체 기간 기준이에요.
      </p>
      {shown.map((f, i) => (
        <RankRow
          key={`${f.artist}|${f.name}`}
          rank={i + 1}
          item={{ name: f.name, artist: f.artist, album: f.album, count: f.scrobbles, duration: f.duration }}
          max={max}
          kind="track"
          onOpen={() => onOpen(f)}
          barText={`${f.scrobbles.toLocaleString()}회 · 처음 ${f.first_played}`}
        />
      ))}
      {missing.length > 0 && (
        <section style={{ marginTop: "1.5rem" }}>
          <h4 style={{ fontWeight: 400, color: "#999", margin: "0 0 0.3rem" }}>기록에서 찾지 못한 곡 ({missing.length})</h4>
          <p style={{ color: "#999", fontSize: "0.8rem", margin: "0 0 0.4rem" }}>이름이 기록과 다르게 저장됐거나 아직 한 번도 안 들은 곡이에요. 기록에 있는 이름으로 다시 ♥ 하세요.</p>
          {missing.map((f) => (
            <div key={`${f.artist}|${f.name}`} style={{ display: "flex", alignItems: "center", gap: "0.6rem", padding: "0.45rem 0.25rem", borderBottom: LINE }}>
              <HeartButton artist={f.artist} name={f.name} />
              <span style={{ fontWeight: 700 }}>{f.name}</span>
              {f.artist && <span style={{ color: "#999" }}>{f.artist}</span>}
            </div>
          ))}
        </section>
      )}
    </>
  );
}
