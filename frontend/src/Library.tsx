import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { BASE_URL } from "./config";
import { Cover } from "./Cover";
import { LINE, RankRow, fmtDuration } from "./RankRow";
import { fmtHM } from "./format";

// Last.fm 라이브러리처럼: 순위 목록(막대) → 아티스트 / 앨범 / 곡 상세 → 곡의 청취 기록

type Category = "artist" | "album" | "track";

type Item = { name: string; artist: string | null; album?: string | null; count: number; duration?: number | null; seconds?: number };

type ListResult = { category: Category; total: number; total_plays: number; offset: number; items: Item[] };

type ArtistDetail = { name: string; scrobbles: number; seconds: number; albums_count: number; tracks_count: number; albums: Item[]; tracks: Item[] };

type AlbumDetail = { name: string; artist: string | null; scrobbles: number; seconds: number; tracks_count: number; tracks: Item[] };

type Play = { time: string; album: string | null; artist: string | null; source: string | null };

type TrackDetail = {
  name: string;
  artist: string | null;
  album: string | null;
  scope_album: string | null;
  albums: { name: string; count: number }[];
  duration?: number | null;
  scrobbles: number;
  seconds: number;
  first_played: string;
  last_played: string;
  offset: number;
  plays: Play[];
};

type View =
  | { type: "list"; category: Category }
  | { type: "artist"; name: string }
  | { type: "album"; name: string; artist: string | null }
  | { type: "track"; name: string; artist: string | null; album: string | null };   // album: 이 앨범에서 들은 기록만 (앨범 페이지에서 열 때)

const PAGE = 50;
const PREVIEW = 10;

const label: CSSProperties = { fontSize: "0.72rem", fontWeight: 700, letterSpacing: "0.03em", color: "#999", textTransform: "uppercase" };
const bigNumber: CSSProperties = { fontSize: "1.5rem", fontWeight: 700 };

function Stat({ title, value }: { title: string; value: string | number }) {
  return (
    <div>
      <div style={label}>{title}</div>
      <div style={bigNumber}>{typeof value === "number" ? value.toLocaleString() : value}</div>
    </div>
  );
}

// 앞쪽 N개만 보여 주다가 "더 보기"로 전부 펼치는 순위 구역 (아티스트 상세의 앨범/곡)
function RankSection({ title, items, kind, onOpen, showArtist = false }: { title: string; items: Item[]; kind: Category; onOpen: (i: Item) => void; showArtist?: boolean }) {
  const [all, setAll] = useState(false);
  if (items.length === 0) return null;
  const shown = all ? items : items.slice(0, PREVIEW);
  const max = items[0].count;
  return (
    <section style={{ marginTop: "1.5rem" }}>
      <h3 style={{ fontWeight: 400 }}>{title}</h3>
      {shown.map((it, i) => (
        <RankRow key={`${it.artist}|${it.name}`} rank={i + 1} item={it} max={max} kind={kind} showArtist={showArtist} onOpen={() => onOpen(it)} />
      ))}
      {items.length > PREVIEW && (
        <div style={{ textAlign: "right", marginTop: "0.5rem" }}>
          <button onClick={() => setAll(!all)} style={{ background: "none", border: "none", color: "#6a9bd8", cursor: "pointer" }}>
            {all ? "접기" : `더 보기 (${items.length}개)`}
          </button>
        </div>
      )}
    </section>
  );
}

function LinkButton({ children, onClick }: { children: ReactNode; onClick: () => void }) {
  return (
    <button onClick={onClick} style={{ background: "none", border: "none", padding: 0, color: "#6a9bd8", cursor: "pointer", font: "inherit" }}>
      {children}
    </button>
  );
}

export function Library({ query }: { query: (extra?: Record<string, string | number>) => string }) {
  const [stack, setStack] = useState<View[]>([{ type: "list", category: "artist" }]);
  const [metric, setMetric] = useState<"plays" | "time">("plays");      // 목록 순위 기준: 재생 횟수 / 청취 시간
  const view = stack[stack.length - 1];

  const go = (v: View) => setStack((s) => [...s, v]);
  const back = () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s));
  const openItem = (kind: Category, it: Item, scopeToAlbum = false) => {
    if (kind === "artist") go({ type: "artist", name: it.name });
    else if (kind === "album") go({ type: "album", name: it.name, artist: it.artist });
    else go({ type: "track", name: it.name, artist: it.artist, album: scopeToAlbum ? (it.album ?? null) : null });
  };

  return (
    <div style={{ textAlign: "left", maxWidth: 980, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap", marginBottom: "1rem" }}>
        {stack.length > 1 && (
          <button onClick={back} style={{ padding: "0.35rem 0.8rem" }}>
            ← 뒤로
          </button>
        )}
        {(["artist", "album", "track"] as Category[]).map((c) => {
          const active = stack[0].type === "list" && (stack[0] as { category: Category }).category === c && stack.length === 1;
          return (
            <button
              key={c}
              onClick={() => setStack([{ type: "list", category: c }])}
              style={{ padding: "0.35rem 0.9rem", fontWeight: active ? 700 : 400, border: active ? "2px solid #8884d8" : "1px solid #666" }}
            >
              {c === "artist" ? "Artists" : c === "album" ? "Albums" : "Tracks"}
            </button>
          );
        })}
      </div>

      {view.type === "list" && (
        <>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", marginBottom: "0.8rem", flexWrap: "wrap" }}>
            {([
              ["plays", "재생 횟수 순"],
              ["time", "청취 시간 순"],
            ] as const).map(([m, text]) => (
              <button
                key={m}
                onClick={() => setMetric(m)}
                style={{ padding: "0.25rem 0.7rem", fontSize: "0.85rem", fontWeight: metric === m ? 700 : 400, border: metric === m ? "2px solid #8884d8" : "1px solid #666" }}
              >
                {text}
              </button>
            ))}
            {metric === "time" && <span style={{ color: "#999", fontSize: "0.8rem" }}>스크로블 횟수 × 곡 길이 (끝까지 들었다고 가정한 추정치)</span>}
          </div>
          <ListView key={`${view.category}|${metric}`} category={view.category} metric={metric} query={query} onOpen={(it) => openItem(view.category, it)} />
        </>
      )}
      {view.type === "artist" && <ArtistView key={view.name} name={view.name} query={query} onOpen={openItem} />}
      {view.type === "album" && <AlbumView key={`${view.artist}|${view.name}`} name={view.name} artist={view.artist} query={query} onOpen={openItem} onArtist={(n) => go({ type: "artist", name: n })} />}
      {view.type === "track" && (
        <TrackView
          key={`${view.artist}|${view.name}|${view.album}`}
          name={view.name}
          artist={view.artist}
          album={view.album}
          query={query}
          onArtist={(n) => go({ type: "artist", name: n })}
          onAlbum={(n, a) => go({ type: "album", name: n, artist: a })}
        />
      )}
    </div>
  );
}

function useFetched<T>(path: string, deps: unknown[]) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    fetch(`${BASE_URL}${path}`)
      .then((res) => res.json())
      .then((d) => {
        if (cancelled) return;
        if (d.error) setError(d.error);
        else setData(d as T);
      })
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { data, error };
}

function ListView({ category, metric, query, onOpen }: { category: Category; metric: "plays" | "time"; query: (e?: Record<string, string | number>) => string; onOpen: (i: Item) => void }) {
  const [items, setItems] = useState<Item[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    (offset: number) => {
      setLoading(true);
      fetch(`${BASE_URL}/api/library/list${query({ category, offset, limit: PAGE, metric })}`)
        .then((res) => res.json())
        .then((d: ListResult & { error?: string }) => {
          if (d.error) return setError(d.error);
          setTotal(d.total);
          setItems((prev) => (offset === 0 ? d.items : [...prev, ...d.items]));
        })
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));
    },
    [category, metric, query]
  );

  useEffect(() => {
    setItems([]);
    setTotal(null);
    load(0);
  }, [load]);

  const noun = category === "artist" ? "Artists" : category === "album" ? "Albums" : "Tracks";
  const byTime = metric === "time";
  const max = (byTime ? items[0]?.seconds : items[0]?.count) ?? 1;
  return (
    <>
      <div style={label}>{noun} scrobbled</div>
      <div style={{ ...bigNumber, marginBottom: "1rem" }}>{total === null ? "…" : total.toLocaleString()}</div>
      {error && <p style={{ color: "#d66" }}>{error}</p>}
      {items.map((it, i) => (
        <RankRow
          key={`${it.artist}|${it.name}`}
          rank={i + 1}
          item={it}
          max={max}
          kind={category}
          onOpen={() => onOpen(it)}
          barFraction={byTime ? (it.seconds ?? 0) / Math.max(1, max) : undefined}
          barText={byTime ? `${fmtHM(it.seconds ?? 0)} · ${it.count.toLocaleString()}회` : undefined}
        />
      ))}
      {total !== null && items.length < total && (
        <div style={{ textAlign: "center", margin: "1rem 0" }}>
          <button disabled={loading} onClick={() => load(items.length)} style={{ padding: "0.5rem 1.2rem" }}>
            {loading ? "불러오는 중..." : `더 보기 (${items.length}/${total})`}
          </button>
        </div>
      )}
    </>
  );
}

function ArtistView({ name, query, onOpen }: { name: string; query: (e?: Record<string, string | number>) => string; onOpen: (k: Category, i: Item) => void }) {
  const { data, error } = useFetched<ArtistDetail>(`/api/library/artist${query({ name })}`, [name, query]);
  if (error) return <p style={{ color: "#d66" }}>{error}</p>;
  if (!data) return <p style={{ color: "#999" }}>불러오는 중...</p>;
  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
        <Cover kind="artist" artist={data.name} size={72} />
        <h2 style={{ margin: 0 }}>{data.name}</h2>
      </div>
      <div style={{ display: "flex", gap: "2rem", margin: "1.2rem 0" }}>
        <Stat title="Scrobbles" value={data.scrobbles} />
        <Stat title="Time" value={fmtHM(data.seconds)} />
        <Stat title="Albums" value={data.albums_count} />
        <Stat title="Tracks" value={data.tracks_count} />
      </div>
      <RankSection title="Albums" items={data.albums} kind="album" onOpen={(i) => onOpen("album", i)} />
      <RankSection title="Tracks" items={data.tracks} kind="track" onOpen={(i) => onOpen("track", i)} />
    </>
  );
}

function AlbumView({
  name,
  artist,
  query,
  onOpen,
  onArtist,
}: {
  name: string;
  artist: string | null;
  query: (e?: Record<string, string | number>) => string;
  onOpen: (k: Category, i: Item, scopeToAlbum?: boolean) => void;
  onArtist: (n: string) => void;
}) {
  const { data, error } = useFetched<AlbumDetail>(`/api/library/album${query({ name, artist: artist ?? "" })}`, [name, artist, query]);
  if (error) return <p style={{ color: "#d66" }}>{error}</p>;
  if (!data) return <p style={{ color: "#999" }}>불러오는 중...</p>;
  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
        <Cover kind="album" artist={data.artist} album={data.name} size={72} />
        <div>
          <h2 style={{ margin: 0 }}>{data.name}</h2>
          {data.artist && <LinkButton onClick={() => onArtist(data.artist as string)}>{data.artist}</LinkButton>}
        </div>
      </div>
      <div style={{ display: "flex", gap: "2rem", margin: "1.2rem 0" }}>
        <Stat title="Scrobbles" value={data.scrobbles} />
        <Stat title="Time" value={fmtHM(data.seconds)} />
        <Stat title="Tracks" value={data.tracks_count} />
      </div>
      <RankSection title="Tracks" items={data.tracks} kind="track" onOpen={(i) => onOpen("track", i, true)} />
    </>
  );
}

function TrackView({
  name,
  artist,
  album,
  query,
  onArtist,
  onAlbum,
}: {
  name: string;
  artist: string | null;
  album: string | null;
  query: (e?: Record<string, string | number>) => string;
  onArtist: (n: string) => void;
  onAlbum: (n: string, a: string | null) => void;
}) {
  const [plays, setPlays] = useState<Play[]>([]);
  const [head, setHead] = useState<TrackDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  // 같은 곡이 여러 앨범에 있으면(원곡/어레인지 앨범 등) "이 앨범만"과 "모든 앨범"을 고를 수 있다
  const [scope, setScope] = useState<string | null>(album);

  const load = useCallback(
    (offset: number) => {
      setLoading(true);
      fetch(`${BASE_URL}/api/library/track${query({ name, artist: artist ?? "", offset, limit: PAGE, album: scope ?? "" })}`)
        .then((res) => res.json())
        .then((d: TrackDetail & { error?: string }) => {
          if (d.error) return setError(d.error);
          if (offset === 0) setHead(d);
          setPlays((prev) => (offset === 0 ? d.plays : [...prev, ...d.plays]));
        })
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));
    },
    [name, artist, scope, query]
  );

  useEffect(() => {
    setPlays([]);
    setError(null);
    load(0);
  }, [load]);

  if (error) return <p style={{ color: "#d66" }}>{error}</p>;
  if (!head) return <p style={{ color: "#999" }}>불러오는 중...</p>;
  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
        <Cover kind="album" artist={head.artist} album={head.album} size={72} />
        <div>
          <h2 style={{ margin: 0 }}>
            {head.name}
            {head.duration ? <span style={{ fontWeight: 400, color: "#999" }}> ({fmtDuration(head.duration)})</span> : null}
          </h2>
          <div>
            {head.artist && <LinkButton onClick={() => onArtist(head.artist as string)}>{head.artist}</LinkButton>}
            {head.album && (
              <span style={{ color: "#999" }}>
                {" · "}
                <LinkButton onClick={() => onAlbum(head.album as string, head.artist)}>{head.album}</LinkButton>
              </span>
            )}
          </div>
        </div>
      </div>
      <div style={{ display: "flex", gap: "2rem", margin: "1.2rem 0" }}>
        <Stat title="Scrobbles" value={head.scrobbles} />
        <Stat title="Time" value={fmtHM(head.seconds)} />
        <Stat title="First" value={head.first_played} />
        <Stat title="Last" value={head.last_played} />
      </div>
      {head.albums.length > 1 && (
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap", marginBottom: "1rem" }}>
          <span style={{ color: "#999", fontSize: "0.85rem" }}>이 곡은 {head.albums.length}개 앨범에 들어 있어요:</span>
          {[
            { label: `모든 앨범 (${head.albums.reduce((a, b) => a + b.count, 0)})`, value: null as string | null },
            ...head.albums.map((a) => ({ label: `${a.name} (${a.count})`, value: a.name as string | null })),
          ].map((o) => (
            <button
              key={o.label}
              onClick={() => setScope(o.value)}
              style={{ padding: "0.25rem 0.7rem", fontSize: "0.85rem", fontWeight: scope === o.value ? 700 : 400, border: scope === o.value ? "2px solid #8884d8" : "1px solid #666" }}
            >
              {o.label}
            </button>
          ))}
        </div>
      )}
      {plays.map((p, i) => (
        <div key={i} style={{ display: "flex", gap: "1rem", padding: "0.55rem 0.25rem", borderBottom: LINE, alignItems: "baseline" }}>
          <span style={{ fontWeight: 700, flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{head.name}</span>
          <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.album ?? ""}</span>
          {p.source && (
            <span title={p.source === "A" ? "Apple Music 기록 유래" : "Last.fm 기록"} style={{ fontSize: "0.7rem", color: "#999", border: LINE, borderRadius: 3, padding: "0 4px" }}>
              {p.source}
            </span>
          )}
          <span style={{ color: "#999", whiteSpace: "nowrap" }}>{p.time}</span>
        </div>
      ))}
      {plays.length < head.scrobbles && (
        <div style={{ textAlign: "center", margin: "1rem 0" }}>
          <button disabled={loading} onClick={() => load(plays.length)} style={{ padding: "0.5rem 1.2rem" }}>
            {loading ? "불러오는 중..." : `더 보기 (${plays.length}/${head.scrobbles})`}
          </button>
        </div>
      )}
    </>
  );
}
