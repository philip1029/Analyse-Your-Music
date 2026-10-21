import { useCallback, useEffect, useState, type CSSProperties, type ReactNode } from "react";
import { BASE_URL } from "./config";
import { Cover } from "./Cover";
import { LINE, RankRow, fmtDuration } from "./RankRow";
import { agoText, fmtHM } from "./format";
import { ConsistencyLine, Sparkline, type ConsistencyResult, type TopItem } from "./Consistency";
import { DiscoveryList } from "./DiscoveryList";
import { Num, Skeleton } from "./motion";
import { ShareButton } from "./Share";
import { CAT } from "./theme";
import { CoverEditor, MissingCovers, type CoverTarget } from "./CoverFix";
import { MissingArtists } from "./ArtistFix";
import { MergeArtists } from "./ArtistMerge";
import { MergeTitles } from "./TitleMerge";

// Last.fm 라이브러리처럼: 순위 목록(막대) → 아티스트 / 앨범 / 곡 상세 → 곡의 청취 기록

type Category = "artist" | "album" | "track";

type Item = { name: string; artist: string | null; album?: string | null; count: number; duration?: number | null; seconds?: number };

type ListResult = { category: Category; total: number; total_plays: number; offset: number; items: Item[] };

type Rank = { plays: number | null; time: number | null; total: number };

type ArtistDetail = { name: string; rank?: Rank; scrobbles: number; seconds: number; first_played: string; last_played: string; albums_count: number; tracks_count: number; albums: Item[]; tracks: Item[] };

type AlbumDetail = { name: string; rank?: Rank; artist: string | null; scrobbles: number; seconds: number; first_played: string; last_played: string; tracks_count: number; tracks: Item[] };

type Play = { time: string; album: string | null; artist: string | null; source: string | null };

type TrackDetail = {
  name: string;
  rank?: Rank;
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

export type SortMode = "plays" | "time" | "even" | "biased" | "first";

const SORTS: { id: SortMode; label: string; hint?: string }[] = [
  { id: "plays", label: "많이 들은 순" },
  { id: "time", label: "오래 들은 순", hint: "청취 시간 = 스크로블 횟수 × 곡 길이 (끝까지 들었다고 가정한 추정치). 긴 곡·긴 앨범이 위로 올라옵니다." },
  { id: "even", label: "꾸준히 들은 순", hint: "처음 들은 달부터 지금까지 월별 재생이 가장 고르게 퍼진 순입니다. 지금은 안 듣는 항목은 마지막 달들이 비어 점수가 내려갑니다." },
  { id: "biased", label: "몰아 들은 순", hint: "한 시기에 몰아서 들은 항목이 위로 옵니다 (월별 재생이 가장 한쪽에 치우친 순)." },
  { id: "first", label: "처음 들은 순", hint: "처음 들은 날짜가 최근인 순 (새로 발견한 항목)." },
];

type View =
  | { type: "top" }
  | { type: "list"; category: Category }
  | { type: "covers" }
  | { type: "artists" }
  | { type: "merge"; target?: "artist" | "album" | "track"; artist?: string }
  | { type: "artist"; name: string }
  | { type: "album"; name: string; artist: string | null }
  | { type: "track"; name: string; artist: string | null; album: string | null };   // album: 이 앨범에서 들은 기록만 (앨범 페이지에서 열 때)

const PAGE = 50;
const PREVIEW = 10;

const label: CSSProperties = { fontSize: "0.72rem", fontWeight: 700, letterSpacing: "0.03em", color: "#999", textTransform: "uppercase" };
const bigNumber: CSSProperties = { fontSize: "1.5rem", fontWeight: 700, whiteSpace: "nowrap" };

function Stat({ title, value, sub }: { title: string; value: string | number; sub?: string }) {
  return (
    <div>
      <div style={label}>{title}</div>
      <div style={bigNumber}>{typeof value === "number" ? <Num value={value} /> : value}</div>
      {sub && <div style={{ color: "#999", fontSize: "0.85rem" }}>{sub}</div>}
    </div>
  );
}

// 전체 중 순위를 눈에 띄게 (재생 횟수 순위 / 청취 시간 순위). 순위는 선택한 기간 안의 기록 기준
function RankStats({ rank, noun }: { rank?: Rank; noun: string }) {
  if (!rank || rank.plays === null) return null;
  const total = `${rank.total.toLocaleString()}${noun} 중`;
  return (
    <>
      <Stat title="Rank · 재생" value={`#${rank.plays.toLocaleString()}`} sub={total} />
      {rank.time !== null && <Stat title="Rank · 시간" value={`#${rank.time.toLocaleString()}`} sub={total} />}
    </>
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
      <h3 style={{ fontWeight: 400, borderLeft: `4px solid ${CAT[kind].main}`, paddingLeft: "0.6rem" }}>{title}</h3>
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

// 다른 탭(Music, Discovery)에서 항목을 눌러 Library 의 상세 페이지로 바로 들어올 때 쓴다
export type LibraryTarget =
  | { kind: "artist"; name: string }
  | { kind: "album"; name: string; artist: string | null }
  | { kind: "track"; name: string; artist: string | null; album?: string | null };
// target: 상세 페이지로 바로 이동 / list: 정렬을 정해 목록으로 이동
export type LibraryRequest = { id: number; target?: LibraryTarget; list?: { category: Category; sort: SortMode } };

export function Library({ query, request }: { query: (extra?: Record<string, string | number>) => string; request?: LibraryRequest | null }) {
  const [stack, setStack] = useState<View[]>([{ type: "top" }]);
  const [sort, setSort] = useState<SortMode>("plays");          // 목록·Top 10 정렬 기준
  const [minPlays, setMinPlays] = useState(20);                   // 꾸준함/몰림 순위의 후보 기준
  const [minMonths, setMinMonths] = useState(12);

  // 요청이 오면 "목록 → 상세"로 쌓아서, 뒤로 가기를 누르면 그 종류의 목록으로 돌아간다
  useEffect(() => {
    if (!request) return;
    if (request.list) {
      setSort(request.list.sort);
      setStack([{ type: "list", category: request.list.category }]);
      return;
    }
    const t = request.target;
    if (!t) return;
    const detail: View =
      t.kind === "artist" ? { type: "artist", name: t.name } : t.kind === "album" ? { type: "album", name: t.name, artist: t.artist } : { type: "track", name: t.name, artist: t.artist, album: t.album ?? null };
    setStack([{ type: "list", category: t.kind }, detail]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [request?.id]);
  const view = stack[stack.length - 1];

  const go = (v: View) => setStack((s) => [...s, v]);
  const back = () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s));
  const openItem = (kind: Category, it: Item, scopeToAlbum = false) => {
    if (kind === "artist") go({ type: "artist", name: it.name });
    else if (kind === "album") go({ type: "album", name: it.name, artist: it.artist });
    else go({ type: "track", name: it.name, artist: it.artist, album: scopeToAlbum ? (it.album ?? null) : null });
  };
  const openTarget = (t: LibraryTarget) =>
    t.kind === "artist" ? go({ type: "artist", name: t.name }) : t.kind === "album" ? go({ type: "album", name: t.name, artist: t.artist }) : go({ type: "track", name: t.name, artist: t.artist, album: t.album ?? null });

  const atRoot = stack.length === 1;
  const catButton = (c: Category) => {
    const active = atRoot && view.type === "list" && view.category === c;
    return (
      <button
        key={c}
        onClick={() => setStack([{ type: "list", category: c }])}
        style={{
          padding: "0.35rem 0.9rem",
          fontWeight: active ? 700 : 400,
          // 카테고리 색 밑줄(비활성이어도 어떤 색인지 보인다). border 단축 속성과 borderBottom 을 섞으면 React 가 경고해서 풀어서 쓴다.
          borderStyle: "solid",
          borderWidth: active ? "2px 2px 3px 2px" : "1px 1px 3px 1px",
          borderColor: active ? CAT[c].main : `#666 #666 ${CAT[c].main} #666`,
          color: active ? CAT[c].main : undefined,
        }}
      >
        {c === "artist" ? "Artists" : c === "album" ? "Albums" : "Tracks"}
      </button>
    );
  };

  const showSortBar = view.type === "top" || view.type === "list";
  const sortInfo = SORTS.find((x) => x.id === sort);

  return (
    <div style={{ textAlign: "left", maxWidth: 980, margin: "0 auto" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", flexWrap: "wrap", marginBottom: "1rem" }}>
        {stack.length > 1 && (
          <button onClick={back} style={{ padding: "0.35rem 0.8rem" }}>
            ← 뒤로
          </button>
        )}
        <button
          onClick={() => setStack([{ type: "top" }])}
          style={{ padding: "0.35rem 0.9rem", fontWeight: atRoot && view.type === "top" ? 700 : 400, border: atRoot && view.type === "top" ? "2px solid #8884d8" : "1px solid #666" }}
        >
          Top 10
        </button>
        {(["artist", "album", "track"] as Category[]).map(catButton)}
        <button
          onClick={() => setStack([{ type: "merge", target: "artist" }])}
          title="이름이 다르게 적힌 같은 아티스트·앨범·곡을 하나로 합치기"
          style={{ padding: "0.35rem 0.9rem", marginLeft: "auto", fontWeight: view.type === "merge" ? 700 : 400, border: view.type === "merge" ? "2px solid #8884d8" : "1px solid #666" }}
        >
          병합
        </button>
        <button
          onClick={() => setStack([{ type: "artists" }])}
          title="아티스트가 비어 있는 기록을 직접 채우기"
          style={{ padding: "0.35rem 0.9rem", fontWeight: view.type === "artists" ? 700 : 400, border: view.type === "artists" ? "2px solid #8884d8" : "1px solid #666" }}
        >
          아티스트 누락
        </button>
        <button
          onClick={() => setStack([{ type: "covers" }])}
          title="자동으로 못 찾은 커버를 직접 지정"
          style={{ padding: "0.35rem 0.9rem", fontWeight: view.type === "covers" ? 700 : 400, border: view.type === "covers" ? "2px solid #8884d8" : "1px solid #666" }}
        >
          커버 누락
        </button>
      </div>

      {showSortBar && (
        <div style={{ marginBottom: "0.8rem" }}>
          <div style={{ display: "flex", gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
            {SORTS.map((o) => (
              <button
                key={o.id}
                onClick={() => setSort(o.id)}
                style={{ padding: "0.25rem 0.7rem", fontSize: "0.85rem", fontWeight: sort === o.id ? 700 : 400, border: sort === o.id ? "2px solid #8884d8" : "1px solid #666" }}
              >
                {o.label}
              </button>
            ))}
            {view.type === "list" && (sort === "plays" || sort === "time") && (
              <span style={{ marginLeft: "auto" }}>
                <ShareButton spec={{ kind: "period", card: "top", period: "all", cat: view.category, metric: sort }} label="🖼 Top 이미지" />
              </span>
            )}
          </div>
          {sortInfo?.hint && <p style={{ color: "#999", fontSize: "0.8rem", margin: "0.5rem 0 0" }}>{sortInfo.hint}</p>}
          {(sort === "even" || sort === "biased") && (
            <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "center", margin: "0.6rem 0 0", color: "#999", fontSize: "0.85rem" }}>
              <label>
                최소 재생{" "}
                <input type="number" min={5} value={minPlays} style={{ width: 64 }} onChange={(e) => setMinPlays(Math.max(5, Number(e.target.value) || 5))} />
                회
              </label>
              <label>
                최소 기간{" "}
                <input type="number" min={2} value={minMonths} style={{ width: 56 }} onChange={(e) => setMinMonths(Math.max(2, Number(e.target.value) || 2))} />
                개월
              </label>
            </div>
          )}
        </div>
      )}

      {view.type === "top" && (
        <TopView
          key={`${sort}|${minPlays}|${minMonths}`}
          sort={sort}
          minPlays={minPlays}
          minMonths={minMonths}
          query={query}
          onOpen={openItem}
          onTarget={openTarget}
          onAll={(c) => setStack([{ type: "list", category: c }])}
        />
      )}
      {view.type === "list" && (
        <ListView
          key={`${view.category}|${sort}|${minPlays}|${minMonths}`}
          category={view.category}
          sort={sort}
          minPlays={minPlays}
          minMonths={minMonths}
          query={query}
          onOpen={(it) => openItem(view.category, it)}
          onTarget={openTarget}
        />
      )}
      {view.type === "covers" && <MissingCovers />}
      {view.type === "artists" && <MissingArtists />}
      {view.type === "merge" && (
        <>
          <div style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
            {(["artist", "album", "track"] as const).map((k) => {
              const active = (view.target ?? "artist") === k;
              return (
                <button
                  key={k}
                  onClick={() => setStack([{ type: "merge", target: k, artist: view.artist }])}
                  style={{
                    padding: "0.3rem 0.9rem",
                    fontWeight: active ? 700 : 400,
                    borderStyle: "solid",
                    borderWidth: active ? "2px 2px 3px 2px" : "1px 1px 3px 1px",
                    borderColor: active ? CAT[k].main : `#666 #666 ${CAT[k].main} #666`,
                    color: active ? CAT[k].main : undefined,
                  }}
                >
                  {k === "artist" ? "아티스트" : k === "album" ? "앨범" : "곡"}
                </button>
              );
            })}
          </div>
          {(view.target ?? "artist") === "artist" ? (
            <MergeArtists onPair={(a) => setStack([{ type: "merge", target: "album", artist: a }])} />
          ) : (
            <MergeTitles
              key={`${view.target}|${view.artist ?? ""}`}
              kind={view.target as "album" | "track"}
              initialArtist={view.artist ?? ""}
              onOtherKind={(k, a) => setStack([{ type: "merge", target: k, artist: a }])}
            />
          )}
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

type RankedRow = { key: string; item: Item; barFraction?: number; barText?: string; extra?: ReactNode };

// 정렬 기준에 따라 알맞은 API 에서 순위 줄을 가져온다. paged: 전체 목록(50개씩 더 보기) / 아니면 Top 10 요약(꾸준함 그래프 포함)
function useRanked(category: Category, sort: SortMode, minPlays: number, minMonths: number, query: (e?: Record<string, string | number>) => string, paged: boolean) {
  const [rows, setRows] = useState<RankedRow[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const size = paged ? PAGE : PREVIEW;

  const load = useCallback(
    (offset: number) => {
      setLoading(true);
      setError(null);
      const done = () => setLoading(false);
      const fail = (e: Error) => setError(e.message);
      const merge = (next: RankedRow[]) => setRows((prev) => (offset === 0 ? next : [...prev, ...next]));

      if (sort === "even" || sort === "biased") {
        fetch(`${BASE_URL}/api/music/consistency${query({ category, sort, min_plays: minPlays, min_months: minMonths, limit: offset + size })}`)
          .then((r) => r.json())
          .then((d: ConsistencyResult & { error?: string }) => {
            if (d.error) return setError(d.error);
            setTotal(d.total_candidates);
            setNote(d.months.length ? `${d.months[0]} ~ ${d.months[d.months.length - 1]} 기준` : null);
            merge(
              d.results.slice(offset).map((r) => ({
                key: r.key,
                item: { name: r.name, artist: r.artist, album: r.album, count: r.plays },
                barFraction: r.evenness ?? 0,
                barText: r.evenness === null ? "-" : `${Math.round(r.evenness * 100)}%`,
                extra: (
                  <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 2, marginTop: 3 }}>
                    <Sparkline monthly={r.monthly} months={d.months} width={Math.min(120, d.months.length * 4)} height={16} />
                    <span style={{ color: "#888", fontSize: "0.75rem" }}>
                      {r.plays.toLocaleString()}회 · {r.first_month} 시작 · {r.active_months}/{r.months}개월 청취 · 최다 {r.peak_month} ({Math.round(r.peak_share * 100)}%)
                      {r.months_since_last >= 1 ? ` · 마지막 청취 ${r.months_since_last}개월 전` : ""}
                    </span>
                  </div>
                ),
              }))
            );
          })
          .catch(fail)
          .finally(done);
      } else if (paged) {
        fetch(`${BASE_URL}/api/library/list${query({ category, offset, limit: size, metric: sort })}`)
          .then((r) => r.json())
          .then((d: ListResult & { error?: string }) => {
            if (d.error) return setError(d.error);
            setTotal(d.total);
            const byTime = sort === "time";
            const max = (byTime ? d.items[0]?.seconds : d.items[0]?.count) ?? 1;
            merge(
              d.items.map((it) => ({
                key: `${it.artist}|${it.name}`,
                item: it,
                barFraction: byTime ? (it.seconds ?? 0) / Math.max(1, max) : undefined,
                barText: byTime ? `${fmtHM(it.seconds ?? 0)} · ${it.count.toLocaleString()}회` : undefined,
              }))
            );
          })
          .catch(fail)
          .finally(done);
      } else {
        // Top 10 요약: 항목마다 월별 재생 그래프(꾸준함)를 함께 보여 준다
        fetch(`${BASE_URL}/api/music/top${query({ category, limit: size, metric: sort })}`)
          .then((r) => r.json())
          .then((d: { error?: string; months: string[]; results: TopItem[] }) => {
            if (d.error) return setError(d.error);
            const byTime = sort === "time";
            const max = (byTime ? d.results[0]?.seconds : d.results[0]?.count) ?? 1;
            setTotal(d.results.length);
            merge(
              d.results.map((it) => ({
                key: `${it.artist}|${it.name}`,
                item: it,
                barFraction: byTime ? (it.seconds ?? 0) / Math.max(1, max) : undefined,
                barText: byTime ? fmtHM(it.seconds ?? 0) : undefined,
                extra: <ConsistencyLine c={it.consistency} months={d.months} plays={byTime ? it.count : undefined} />,
              }))
            );
          })
          .catch(fail)
          .finally(done);
      }
    },
    [category, sort, minPlays, minMonths, query, paged, size]
  );

  useEffect(() => {
    setRows([]);
    setTotal(null);
    load(0);
  }, [load]);

  return { rows, total, loading, error, note, load };
}

function RankRows({ rows, category, onOpen }: { rows: RankedRow[]; category: Category; onOpen: (i: Item) => void }) {
  const max = rows[0]?.item.count ?? 1;
  return (
    <>
      {rows.map((r, i) => (
        <RankRow key={r.key} rank={i + 1} item={r.item} max={max} kind={category} onOpen={() => onOpen(r.item)} barFraction={r.barFraction} barText={r.barText} extra={r.extra} />
      ))}
    </>
  );
}

function ListView({
  category,
  sort,
  minPlays,
  minMonths,
  query,
  onOpen,
  onTarget,
}: {
  category: Category;
  sort: SortMode;
  minPlays: number;
  minMonths: number;
  query: (e?: Record<string, string | number>) => string;
  onOpen: (i: Item) => void;
  onTarget: (t: LibraryTarget) => void;
}) {
  const noun = category === "artist" ? "Artists" : category === "album" ? "Albums" : "Tracks";
  if (sort === "first") return <DiscoveryList cat={category} query={query} onOpen={onTarget} />;
  return <ListBody category={category} sort={sort} minPlays={minPlays} minMonths={minMonths} query={query} onOpen={onOpen} noun={noun} />;
}

function ListBody({ category, sort, minPlays, minMonths, query, onOpen, noun }: { category: Category; sort: SortMode; minPlays: number; minMonths: number; query: (e?: Record<string, string | number>) => string; onOpen: (i: Item) => void; noun: string }) {
  const { rows, total, loading, error, note, load } = useRanked(category, sort, minPlays, minMonths, query, true);
  const filtered = sort === "even" || sort === "biased";
  return (
    <>
      <div style={label}>{filtered ? `${noun} · 조건에 맞는 항목` : `${noun} scrobbled`}</div>
      <div style={{ ...bigNumber, marginBottom: filtered && note ? "0.2rem" : "1rem" }}>{total === null ? "…" : <Num value={total} />}</div>
      {filtered && note && <div style={{ color: "#999", fontSize: "0.8rem", marginBottom: "1rem" }}>{note}</div>}
      {error && <p style={{ color: "#d66" }}>{error}</p>}
      {total === null && !error && <Skeleton lines={5} height={44} />}
      <RankRows rows={rows} category={category} onOpen={onOpen} />
      {total !== null && rows.length === 0 && filtered && <p style={{ color: "#888" }}>조건에 맞는 항목이 없습니다. 최소 재생·기간을 낮춰 보세요.</p>}
      {total !== null && rows.length < total && (
        <div style={{ textAlign: "center", margin: "1rem 0" }}>
          <button disabled={loading} onClick={() => load(rows.length)} style={{ padding: "0.5rem 1.2rem" }}>
            {loading ? "불러오는 중..." : `더 보기 (${rows.length}/${total})`}
          </button>
        </div>
      )}
    </>
  );
}

// 기본 화면: 아티스트·곡·앨범 Top 10 (정렬 기준은 위 버튼). 각 구역의 "전체 보기"로 전체 목록으로 간다.
function TopView({
  sort,
  minPlays,
  minMonths,
  query,
  onOpen,
  onTarget,
  onAll,
}: {
  sort: SortMode;
  minPlays: number;
  minMonths: number;
  query: (e?: Record<string, string | number>) => string;
  onOpen: (k: Category, i: Item) => void;
  onTarget: (t: LibraryTarget) => void;
  onAll: (c: Category) => void;
}) {
  return (
    <>
      {([
        ["artist", "Artists"],
        ["track", "Tracks"],
        ["album", "Albums"],
      ] as [Category, string][]).map(([kind, title]) => (
        <section key={kind} style={{ marginTop: "1.5rem" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: "1rem", marginBottom: "0.4rem" }}>
            <h3 style={{ fontWeight: 400, margin: "0.6rem 0", borderLeft: `4px solid ${CAT[kind].main}`, paddingLeft: "0.6rem" }}>{title}</h3>
            <span style={{ display: "flex", alignItems: "center", gap: "0.8rem" }}>
              {(sort === "plays" || sort === "time") && <ShareButton spec={{ kind: "period", card: "top", period: "all", cat: kind, metric: sort }} />}
              <LinkButton onClick={() => onAll(kind)}>전체 보기 →</LinkButton>
            </span>
          </div>
          <TopSection category={kind} sort={sort} minPlays={minPlays} minMonths={minMonths} query={query} onOpen={(it) => onOpen(kind, it)} onTarget={onTarget} />
        </section>
      ))}
    </>
  );
}

function TopSection({ category, sort, minPlays, minMonths, query, onOpen, onTarget }: { category: Category; sort: SortMode; minPlays: number; minMonths: number; query: (e?: Record<string, string | number>) => string; onOpen: (i: Item) => void; onTarget: (t: LibraryTarget) => void }) {
  if (sort === "first") return <DiscoveryList cat={category} query={query} onOpen={onTarget} limit={10} />;
  return <TopRows category={category} sort={sort} minPlays={minPlays} minMonths={minMonths} query={query} onOpen={onOpen} />;
}

function TopRows({ category, sort, minPlays, minMonths, query, onOpen }: { category: Category; sort: SortMode; minPlays: number; minMonths: number; query: (e?: Record<string, string | number>) => string; onOpen: (i: Item) => void }) {
  const { rows, total, error } = useRanked(category, sort, minPlays, minMonths, query, false);
  if (error) return <p style={{ color: "#d66" }}>{error}</p>;
  if (total === null) return <Skeleton lines={4} height={44} />;
  if (rows.length === 0) return <p style={{ color: "#888" }}>조건에 맞는 항목이 없습니다. 최소 재생·기간을 낮춰 보세요.</p>;
  return <RankRows rows={rows} category={category} onOpen={onOpen} />;
}

function ArtistView({ name, query, onOpen }: { name: string; query: (e?: Record<string, string | number>) => string; onOpen: (k: Category, i: Item) => void }) {
  const { data, error } = useFetched<ArtistDetail>(`/api/library/artist${query({ name })}`, [name, query]);
  const [editing, setEditing] = useState<CoverTarget | null>(null);
  const [coverVersion, setCoverVersion] = useState(0);
  if (error) return <p style={{ color: "#d66" }}>{error}</p>;
  if (!data) return <Skeleton lines={5} height={30} />;
  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
        <Cover key={coverVersion} kind="artist" artist={data.name} size={72} />
        <h2 style={{ margin: 0, flex: 1 }}>{data.name}</h2>
        <button onClick={() => setEditing({ kind: "artist", artist: data.name, label: data.name })} title="아티스트 사진을 직접 지정" style={{ padding: "0.3rem 0.8rem", fontSize: "0.85rem" }}>
          사진 변경
        </button>
        <ShareButton spec={{ kind: "artist", name: data.name }} />
      </div>
      {editing && <CoverEditor target={editing} onClose={() => setEditing(null)} onSaved={() => setCoverVersion((v) => v + 1)} />}
      <div style={{ display: "flex", gap: "1rem 2rem", flexWrap: "wrap", margin: "1.2rem 0" }}>
        <Stat title="Scrobbles" value={data.scrobbles} />
        <Stat title="Time" value={fmtHM(data.seconds)} />
        <RankStats rank={data.rank} noun="명" />
        <Stat title="Albums" value={data.albums_count} />
        <Stat title="Tracks" value={data.tracks_count} />
        <Stat title="First" value={data.first_played} sub={agoText(data.first_played)} />
        <Stat title="Last" value={data.last_played} sub={agoText(data.last_played)} />
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
  const [editing, setEditing] = useState<CoverTarget | null>(null);
  const [coverVersion, setCoverVersion] = useState(0);
  if (error) return <p style={{ color: "#d66" }}>{error}</p>;
  if (!data) return <Skeleton lines={5} height={30} />;
  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
        <Cover key={coverVersion} kind="album" artist={data.artist} album={data.name} size={72} />
        <div style={{ flex: 1 }}>
          <h2 style={{ margin: 0 }}>{data.name}</h2>
          {data.artist && <LinkButton onClick={() => onArtist(data.artist as string)}>{data.artist}</LinkButton>}
        </div>
        {data.artist && (
          <button
            onClick={() => setEditing({ kind: "album", artist: data.artist as string, album: data.name, label: `${data.name} — ${data.artist}` })}
            title="앨범 커버를 직접 지정"
            style={{ padding: "0.3rem 0.8rem", fontSize: "0.85rem" }}
          >
            커버 변경
          </button>
        )}
        <ShareButton spec={{ kind: "album", name: data.name, artist: data.artist }} />
      </div>
      {editing && <CoverEditor target={editing} onClose={() => setEditing(null)} onSaved={() => setCoverVersion((v) => v + 1)} />}
      <div style={{ display: "flex", gap: "1rem 2rem", flexWrap: "wrap", margin: "1.2rem 0" }}>
        <Stat title="Scrobbles" value={data.scrobbles} />
        <Stat title="Time" value={fmtHM(data.seconds)} />
        <RankStats rank={data.rank} noun="개" />
        <Stat title="Tracks" value={data.tracks_count} />
        <Stat title="First" value={data.first_played} sub={agoText(data.first_played)} />
        <Stat title="Last" value={data.last_played} sub={agoText(data.last_played)} />
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
  if (!head) return <Skeleton lines={5} height={30} />;
  return (
    <>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
        <Cover kind="album" artist={head.artist} album={head.album} size={72} />
        <div style={{ flex: 1 }}>
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
        <ShareButton spec={{ kind: "track", name: head.name, artist: head.artist, album: scope }} />
      </div>
      <div style={{ display: "flex", gap: "1rem 2rem", flexWrap: "wrap", margin: "1.2rem 0" }}>
        <Stat title="Scrobbles" value={head.scrobbles} />
        <Stat title="Time" value={fmtHM(head.seconds)} />
        <RankStats rank={head.rank} noun="곡" />
        <Stat title="First" value={head.first_played} sub={agoText(head.first_played)} />
        <Stat title="Last" value={head.last_played} sub={agoText(head.last_played)} />
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
