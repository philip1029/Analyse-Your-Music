import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { BASE_URL } from "./config";
import { LINE } from "./RankRow";

// 선택한 아티스트·앨범(하나 또는 여러 개)의 기록만 CSV 로 내려받거나 AI 분석용 프롬프트로 만든다.
// 담은 목록은 아티스트·앨범 페이지의 "＋ 선택에 담기"와 Data 탭의 검색으로 채우고, 이 브라우저에 기억한다 (다시 열어도 남는다).

export type SelItem = { kind: "artist" | "album"; name: string; artist: string | null };

const STORE = "aym.selection";
const same = (a: SelItem, b: SelItem) => a.kind === b.kind && a.name === b.name && (a.artist ?? "") === (b.artist ?? "");
export const itemLabel = (i: SelItem) => (i.kind === "album" && i.artist ? `${i.artist} - ${i.name}` : i.name);

function readStore(): SelItem[] {
  try {
    const raw = JSON.parse(localStorage.getItem(STORE) ?? "[]");
    return Array.isArray(raw) ? raw.filter((i) => i && (i.kind === "artist" || i.kind === "album") && typeof i.name === "string") : [];
  } catch {
    return [];
  }
}

type Ctx = { items: SelItem[]; has: (i: SelItem) => boolean; toggle: (i: SelItem) => void; remove: (i: SelItem) => void; clear: () => void };
const SelectionContext = createContext<Ctx | null>(null);
export const useSelection = () => useContext(SelectionContext);

export function SelectionProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<SelItem[]>(readStore);
  useEffect(() => {
    try {
      localStorage.setItem(STORE, JSON.stringify(items));
    } catch {
      /* 저장이 막혀 있어도 이번 방문 동안은 동작한다 */
    }
  }, [items]);
  const value = useMemo<Ctx>(
    () => ({
      items,
      has: (i) => items.some((x) => same(x, i)),
      toggle: (i) => setItems((p) => (p.some((x) => same(x, i)) ? p.filter((x) => !same(x, i)) : [...p, i])),
      remove: (i) => setItems((p) => p.filter((x) => !same(x, i))),
      clear: () => setItems([]),
    }),
    [items]
  );
  return <SelectionContext.Provider value={value}>{children}</SelectionContext.Provider>;
}

// 아티스트·앨범 페이지 위쪽의 토글 버튼
export function SelectionButton({ item }: { item: SelItem }) {
  const sel = useSelection();
  if (!sel) return null;
  const on = sel.has(item);
  return (
    <button
      onClick={() => sel.toggle(item)}
      aria-pressed={on}
      title={on ? "내보내기 선택에서 빼기" : "Data 탭의 '선택 내보내기'에 담기 (CSV·AI 프롬프트)"}
      style={{ padding: "0.3rem 0.8rem", fontSize: "0.85rem", fontWeight: on ? 700 : 400, border: on ? "2px solid #8884d8" : undefined }}
    >
      {on ? `✓ 선택됨 (${sel.items.length})` : "＋ 선택에 담기"}
    </button>
  );
}

type Hit = { name: string; artist: string | null; count: number };
type Summary = { items: (SelItem & { label: string; found: boolean; scrobbles: number; first_played: string | null; last_played: string | null })[]; total: { scrobbles: number; library: number; first_played: string | null; last_played: string | null } };

// Data 탭의 "선택 내보내기" 패널: 검색해서 담고, 담은 항목의 요약을 보고, CSV / AI 프롬프트로 내보낸다.
export function SelectionPanel({ query }: { query: (extra?: Record<string, string | number>) => string }) {
  const sel = useSelection();
  const [text, setText] = useState("");
  const [hits, setHits] = useState<{ artists: Hit[]; albums: Hit[] } | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [prompt, setPrompt] = useState<string | null>(null);
  const [busy, setBusy] = useState<"csv" | "prompt" | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const items = sel?.items ?? [];
  const body = useMemo(() => JSON.stringify({ items }), [items]);
  const range = query();                                          // "?start=…&end=…" (선택한 기간)

  // 입력이 멈추면(0.25초) 아티스트·앨범을 찾는다 (기간과 상관없이 전체에서)
  useEffect(() => {
    const q = text.trim();
    if (!q) return setHits(null);
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      fetch(`${BASE_URL}/api/search?q=${encodeURIComponent(q)}&limit=6`, { signal: ctrl.signal })
        .then((r) => r.json())
        .then((d) => setHits({ artists: d.artists ?? [], albums: d.albums ?? [] }))
        .catch(() => {});
    }, 250);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [text]);

  // 담은 항목이나 기간이 바뀌면 요약을 새로 받는다
  useEffect(() => {
    setPrompt(null);
    setNote(null);
    if (!items.length) return setSummary(null);
    const ctrl = new AbortController();
    fetch(`${BASE_URL}/api/selection/summary${range}`, { method: "POST", headers: { "Content-Type": "application/json" }, body, signal: ctrl.signal })
      .then((r) => r.json())
      .then((d) => !d.error && setSummary(d as Summary))
      .catch(() => {});
    return () => ctrl.abort();
  }, [body, range, items.length]);

  const post = useCallback((path: string) => fetch(`${BASE_URL}${path}${range}`, { method: "POST", headers: { "Content-Type": "application/json" }, body }), [body, range]);

  const downloadCsv = () => {
    setBusy("csv");
    setNote(null);
    post("/api/selection/csv")
      .then(async (r) => {
        if (!r.ok) throw new Error(await r.text());
        const url = URL.createObjectURL(await r.blob());
        const a = Object.assign(document.createElement("a"), { href: url, download: "analyse-your-music_selection.csv" });
        document.body.appendChild(a);
        a.click();
        a.remove();
        URL.revokeObjectURL(url);
      })
      .catch((e) => setNote(`CSV 실패: ${e.message}`))
      .finally(() => setBusy(null));
  };

  const makePrompt = () => {
    setBusy("prompt");
    setNote(null);
    post("/api/selection/prompt")
      .then((r) => r.json())
      .then((d) => (d.error ? setNote(d.error) : setPrompt(d.prompt)))
      .catch((e) => setNote(`프롬프트 실패: ${e.message}`))
      .finally(() => setBusy(null));
  };

  if (!sel) return null;
  const add = (i: SelItem) => !sel.has(i) && sel.toggle(i);
  const row = (i: SelItem, count: number) => (
    <div key={`${i.kind}|${i.artist}|${i.name}`} style={{ display: "flex", gap: "0.6rem", padding: "0.3rem 0.2rem", borderBottom: LINE, alignItems: "center" }}>
      <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{itemLabel(i)}</span>
      <span style={{ color: "#999", fontSize: "0.8rem" }}>{count.toLocaleString()}회</span>
      <button onClick={() => add(i)} disabled={sel.has(i)} style={{ padding: "0.15rem 0.6rem", fontSize: "0.8rem" }}>
        {sel.has(i) ? "담김" : "＋ 담기"}
      </button>
    </div>
  );

  return (
    <div>
      <p style={{ color: "#999", fontSize: "0.85rem", margin: "0 0 0.8rem", lineHeight: 1.6 }}>
        아티스트·앨범을 하나 또는 여러 개 담으면, 그 기록만 CSV 로 내려받거나 그것만 담은 AI 분석용 프롬프트를 만들 수 있어요. 위쪽에서 고른 기간이 그대로 적용돼요
        (아티스트·앨범 페이지의 “＋ 선택에 담기”로도 담을 수 있어요).
      </p>
      <input
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="아티스트·앨범 이름으로 찾아서 담기"
        aria-label="담을 아티스트·앨범 검색"
        style={{ width: "100%", maxWidth: 440, boxSizing: "border-box", padding: "0.5rem 0.7rem" }}
      />
      {hits && (hits.artists.length > 0 || hits.albums.length > 0) && (
        <div style={{ maxWidth: 560, margin: "0.5rem 0 1rem" }}>
          {hits.artists.map((h) => row({ kind: "artist", name: h.name, artist: null }, h.count))}
          {hits.albums.map((h) => row({ kind: "album", name: h.name, artist: h.artist }, h.count))}
        </div>
      )}
      {hits && hits.artists.length === 0 && hits.albums.length === 0 && <p style={{ color: "#999", fontSize: "0.85rem" }}>찾는 아티스트·앨범이 없어요.</p>}

      <div style={{ margin: "1rem 0 0.4rem", display: "flex", alignItems: "center", gap: "0.6rem" }}>
        <strong>담은 항목 {items.length}개</strong>
        {items.length > 0 && (
          <button onClick={sel.clear} style={{ padding: "0.15rem 0.6rem", fontSize: "0.8rem" }}>
            모두 비우기
          </button>
        )}
      </div>
      {items.length === 0 ? (
        <p style={{ color: "#999", fontSize: "0.85rem", margin: 0 }}>아직 담은 항목이 없어요.</p>
      ) : (
        <div style={{ maxWidth: 640 }}>
          {items.map((i) => {
            const s = summary?.items.find((x) => x.kind === i.kind && x.name === i.name && (x.artist ?? "") === (i.artist ?? ""));
            return (
              <div key={`${i.kind}|${i.artist}|${i.name}`} style={{ display: "flex", gap: "0.6rem", padding: "0.35rem 0.2rem", borderBottom: LINE, alignItems: "center" }}>
                <span style={{ fontSize: "0.72rem", color: "#999", width: 44, flexShrink: 0 }}>{i.kind === "artist" ? "아티스트" : "앨범"}</span>
                <span style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{itemLabel(i)}</span>
                <span style={{ color: s && !s.found ? "#d66" : "#999", fontSize: "0.8rem", whiteSpace: "nowrap" }}>
                  {s ? (s.found ? `${s.scrobbles.toLocaleString()}회 · ${s.first_played} ~ ${s.last_played}` : "이 기간에 기록 없음") : ""}
                </span>
                <button onClick={() => sel.remove(i)} aria-label={`${itemLabel(i)} 빼기`} style={{ padding: "0.1rem 0.5rem", fontSize: "0.8rem" }}>
                  ✕
                </button>
              </div>
            );
          })}
          {summary && (
            <p style={{ margin: "0.6rem 0 0", fontSize: "0.9rem" }}>
              합계(겹치는 기록은 한 번만): <strong>{summary.total.scrobbles.toLocaleString()}회</strong> · 전체 {summary.total.library.toLocaleString()}회의{" "}
              {summary.total.library ? ((summary.total.scrobbles / summary.total.library) * 100).toFixed(1) : "0"}%
            </p>
          )}
        </div>
      )}

      <div style={{ display: "flex", gap: "0.6rem", flexWrap: "wrap", marginTop: "1rem" }}>
        <button onClick={downloadCsv} disabled={!items.length || busy !== null} style={{ padding: "0.5rem 1rem" }}>
          {busy === "csv" ? "만드는 중..." : "⬇️ CSV 내려받기"}
        </button>
        <button onClick={makePrompt} disabled={!items.length || busy !== null} style={{ padding: "0.5rem 1rem" }}>
          {busy === "prompt" ? "생성 중..." : "📋 AI 프롬프트 만들기"}
        </button>
      </div>
      {note && <p style={{ color: "#d66", fontSize: "0.85rem", margin: "0.6rem 0 0" }}>{note}</p>}
      {prompt && (
        <div style={{ marginTop: "1rem" }}>
          <textarea readOnly value={prompt} style={{ width: "100%", height: 360, padding: "0.75rem", fontFamily: "monospace", fontSize: "0.8rem", whiteSpace: "pre-wrap", boxSizing: "border-box" }} />
          <button
            onClick={() => {
              navigator.clipboard.writeText(prompt).then(() => {
                setCopied(true);
                setTimeout(() => setCopied(false), 1500);
              });
            }}
            style={{ padding: "0.5rem 1rem", marginTop: "0.5rem" }}
          >
            {copied ? "복사됨!" : "📋 클립보드에 복사"}
          </button>
        </div>
      )}
    </div>
  );
}
