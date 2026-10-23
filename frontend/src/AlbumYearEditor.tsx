import { useCallback, useEffect, useState } from "react";
import { BASE_URL } from "./config";
import { LINE } from "./RankRow";
import { CAT, MUTED } from "./theme";

// 연대별 음악의 발매연도를 직접 입력·수정하는 패널. 저장하면 config/album_years.txt 에 적히고 자동 조회보다 항상 우선한다.

type Item = { artist: string; album: string; plays: number; year: number | null; src: string | null; manual: boolean; ambiguous: boolean; checked: boolean };
type Page = { error?: string; total: number; items: Item[] };

const PAGE = 30;
const SRC_LABEL: Record<string, string> = { musicbrainz: "MusicBrainz", "musicbrainz:apple": "MusicBrainz+Apple", apple: "Apple", manual: "직접 입력" };
const YEAR_MAX = new Date().getFullYear() + 1;
const validYear = (s: string) => /^\d{4}$/.test(s) && Number(s) >= 1900 && Number(s) <= YEAR_MAX;

const smallBtn = (enabled: boolean) => ({
  padding: "0.2rem 0.7rem",
  borderRadius: 999,
  border: LINE,
  background: enabled ? CAT.album.main : "transparent",
  color: enabled ? "#1a1b1e" : MUTED,
  fontWeight: 700,
  fontSize: "0.8rem",
  cursor: enabled ? "pointer" : "default",
});

function Row({ item, onSaved }: { item: Item; onSaved: (next: Item | null, changed: boolean) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = (year: number | null) => {
    setBusy(true);
    setError(null);
    fetch(`${BASE_URL}/api/album-years/override`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ artist: item.artist, album: item.album, year }),
    })
      .then((r) => r.json())
      .then((d) => {
        if (d.error) {
          setError(d.error);
          return;
        }
        setText("");
        onSaved({ ...item, year: d.year, src: d.src, manual: d.src === "manual", checked: true }, true);
      })
      .catch((e) => setError(e.message))
      .finally(() => setBusy(false));
  };

  const ok = validYear(text) && !busy;
  return (
    <li style={{ padding: "0.5rem 0.2rem", borderBottom: LINE, listStyle: "none" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.7rem", flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 200 }}>
          <div style={{ fontWeight: 600, overflowWrap: "anywhere" }}>{item.album}</div>
          <div style={{ color: MUTED, fontSize: "0.82rem", overflowWrap: "anywhere" }}>{item.artist} · {item.plays.toLocaleString()}회</div>
        </div>
        <div style={{ minWidth: 110, textAlign: "right", fontSize: "0.85rem" }}>
          {item.year ? (
            <>
              <strong>{item.year}</strong>
              <span style={{ color: MUTED }}> · {SRC_LABEL[item.src ?? ""] ?? item.src}{item.ambiguous ? " (불확실)" : ""}</span>
            </>
          ) : (
            <span style={{ color: MUTED }}>{item.checked ? "못 찾음" : "조회 전"}</span>
          )}
        </div>
        <input
          value={text}
          onChange={(e) => setText(e.target.value.replace(/\D/g, "").slice(0, 4))}
          onKeyDown={(e) => e.key === "Enter" && ok && send(Number(text))}
          inputMode="numeric"
          placeholder="연도"
          aria-label={`${item.album} 발매연도`}
          style={{ width: 64, padding: "0.25rem 0.4rem", borderRadius: 6, border: LINE, background: "transparent", color: "inherit", textAlign: "center" }}
        />
        <button type="button" disabled={!ok} onClick={() => send(Number(text))} style={smallBtn(ok)}>저장</button>
        {item.manual && (
          <button type="button" disabled={busy} onClick={() => send(null)} style={smallBtn(false)} title="직접 입력한 연도를 지우고 자동 조회 값으로 되돌립니다">지우기</button>
        )}
      </div>
      {error && <div style={{ color: "#e07070", fontSize: "0.82rem", marginTop: "0.25rem" }}>{error}</div>}
    </li>
  );
}

export function AlbumYearEditor({ onChanged }: { onChanged: () => void }) {
  const [onlyUnknown, setOnlyUnknown] = useState(true);
  const [q, setQ] = useState("");
  const [debounced, setDebounced] = useState("");
  const [items, setItems] = useState<Item[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => setDebounced(q.trim()), 300);
    return () => clearTimeout(t);
  }, [q]);

  const load = useCallback(
    (offset: number, append: boolean) => {
      setLoading(true);
      setError(null);
      const params = new URLSearchParams({ unknown: String(onlyUnknown), q: debounced, offset: String(offset), limit: String(PAGE) });
      fetch(`${BASE_URL}/api/album-years/albums?${params}`)
        .then((r) => r.json())
        .then((d: Page) => {
          if (d.error) {
            setError(d.error);
            return;
          }
          setTotal(d.total);
          setItems((cur) => (append ? [...cur, ...d.items] : d.items));
        })
        .catch((e) => setError(e.message))
        .finally(() => setLoading(false));
    },
    [onlyUnknown, debounced],
  );

  useEffect(() => load(0, false), [load]);

  const saved = (index: number, next: Item | null, changed: boolean) => {
    // 연도를 모르는 앨범만 보는 중에 연도가 생기면 목록에서 뺀다
    if (next && onlyUnknown && next.year) {
      setItems((cur) => cur.filter((_, i) => i !== index));
      setTotal((n) => Math.max(0, n - 1));
    } else if (next) {
      setItems((cur) => cur.map((it, i) => (i === index ? next : it)));
    }
    if (changed) onChanged();
  };

  return (
    <div style={{ border: LINE, borderRadius: 8, padding: "0.8rem 1rem", margin: "0.5rem 0 1rem" }}>
      <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap" }}>
        <button type="button" onClick={() => setOnlyUnknown(true)} style={smallBtn(onlyUnknown)}>연도 모르는 앨범</button>
        <button type="button" onClick={() => setOnlyUnknown(false)} style={smallBtn(!onlyUnknown)}>전체 앨범 (틀린 연도 수정)</button>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="앨범·아티스트 검색"
          aria-label="앨범 검색"
          style={{ flex: 1, minWidth: 160, padding: "0.3rem 0.6rem", borderRadius: 6, border: LINE, background: "transparent", color: "inherit" }}
        />
      </div>
      <p style={{ color: MUTED, fontSize: "0.8rem", margin: "0.5rem 0" }}>
        4자리 연도를 입력하고 저장(Enter)하면 <code>config/album_years.txt</code> 에 적히고, 자동 조회보다 항상 우선합니다. 재생 많은 순으로 보여 줍니다.
      </p>
      {error && <p style={{ color: "#e07070" }}>{error}</p>}
      <ul style={{ margin: 0, padding: 0 }}>
        {items.map((it, i) => (
          <Row key={`${it.artist}\t${it.album}`} item={it} onSaved={(next, changed) => saved(i, next, changed)} />
        ))}
      </ul>
      {!loading && items.length === 0 && !error && <p style={{ color: MUTED }}>{onlyUnknown ? "연도를 모르는 앨범이 없어요 🎉" : "찾는 앨범이 없어요."}</p>}
      <div style={{ display: "flex", alignItems: "center", gap: "0.8rem", marginTop: "0.5rem" }}>
        {items.length < total && (
          <button type="button" disabled={loading} onClick={() => load(items.length, true)} style={smallBtn(false)}>더 보기 ({items.length.toLocaleString()} / {total.toLocaleString()})</button>
        )}
        {loading && <span style={{ color: MUTED, fontSize: "0.85rem" }}>불러오는 중…</span>}
      </div>
    </div>
  );
}
