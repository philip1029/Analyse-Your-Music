import { useCallback, useEffect, useState } from "react";
import { ArtistPicker } from "./ArtistMerge";
import { BASE_URL } from "./config";
import { CAT } from "./theme";

// 같은 앨범/곡인데 제목이 다르게 적힌 항목(예: Romance / 로맨스)을 한 아티스트 안에서 합치는 화면.
// 통일 표기는 Last.fm 이 쓰는 표기(L 행이 많은 쪽)를 권한다. 규칙(config/title_merge.txt)이 남아서 새로고침 때도 자동 적용되고, 되돌릴 수 있다.

type Kind = "album" | "track";
type Title = { title: string; A: number; L: number; total: number };
type Stats = { title: string; A: number; L: number; total: number };
type Preview = { variant: Stats; canonical: Stats; suggest_swap: boolean; collisions: number; error: string | null };
type Rule = { kind: Kind; artist: string; variant: string; canonical: string; pending: boolean; restorable: number };

const NOUN: Record<Kind, string> = { album: "앨범", track: "곡" };
const label = (t: Title) => `${t.title}  (Apple ${t.A.toLocaleString()} · Last.fm ${t.L.toLocaleString()})`;
const src = (s: Stats) => `${s.total.toLocaleString()}행 (Apple ${s.A.toLocaleString()} · Last.fm ${s.L.toLocaleString()})`;

export function MergeTitles({ kind }: { kind: Kind }) {
  const [artist, setArtist] = useState("");
  const [titles, setTitles] = useState<Title[]>([]);
  const [variant, setVariant] = useState("");
  const [canonical, setCanonical] = useState("");
  const [prev, setPrev] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);

  const loadRules = useCallback(() => {
    fetch(`${BASE_URL}/api/title-merge/rules`)
      .then((r) => r.json())
      .then((d) => setRules(((d.rules ?? []) as Rule[]).filter((r) => r.kind === kind)))
      .catch(() => {});
  }, [kind]);
  useEffect(loadRules, [loadRules]);

  // 아티스트가 정해지면 그 아티스트의 앨범/곡 표기 목록을 받고, Last.fm 표기를 통일 이름으로 미리 골라 둔다
  const loadTitles = useCallback(
    (a: string) => {
      fetch(`${BASE_URL}/api/title-merge/titles?kind=${kind}&artist=${encodeURIComponent(a)}`)
        .then((r) => r.json())
        .then((d) => {
          const list = (d.titles ?? []) as Title[];
          setTitles(list);
          if (list.length >= 2) {
            const canon = [...list].sort((x, y) => y.L - x.L || y.total - x.total)[0];
            const other = list.find((t) => t.title !== canon.title)!;
            setCanonical(canon.title);
            setVariant(other.title);
          } else {
            setCanonical("");
            setVariant("");
          }
        })
        .catch(() => {});
    },
    [kind]
  );
  useEffect(() => {
    setTitles([]);
    setVariant("");
    setCanonical("");
    setPrev(null);
    const a = artist.trim();
    if (!a) return;
    const timer = setTimeout(() => loadTitles(a), 300);
    return () => clearTimeout(timer);
  }, [artist, loadTitles]);

  useEffect(() => {
    if (!variant || !canonical) {
      setPrev(null);
      return;
    }
    const ctrl = new AbortController();
    fetch(`${BASE_URL}/api/title-merge/preview?kind=${kind}&artist=${encodeURIComponent(artist.trim())}&variant=${encodeURIComponent(variant)}&canonical=${encodeURIComponent(canonical)}`, { signal: ctrl.signal })
      .then((r) => r.json())
      .then((d) => setPrev(d.variant ? (d as Preview) : null))
      .catch(() => {});
    return () => ctrl.abort();
  }, [kind, artist, variant, canonical]);

  const merge = async () => {
    if (!prev || prev.error) return;
    if (!window.confirm(`${artist.trim()} 의 ${NOUN[kind]} ‘${variant}’ 기록 ${prev.variant.total.toLocaleString()}행을 ‘${canonical}’ 로 합칩니다.\n(data CSV 는 먼저 백업돼요)`)) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await (await fetch(`${BASE_URL}/api/title-merge`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind, artist: artist.trim(), variant, canonical }) })).json();
      if (res.error) setMessage(`실패: ${res.error}`);
      else {
        setMessage(`합쳤어요: ‘${res.variant}’ → ‘${res.canonical}’ (${res.applied_rows.toLocaleString()}행${res.backup ? ` · 백업 ${res.backup}` : ""})`);
        loadTitles(artist.trim());
        loadRules();
      }
    } catch (e) {
      setMessage(`실패: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const undo = async (r: Rule) => {
    if (!window.confirm(`${r.artist} 의 ${NOUN[kind]} ‘${r.variant}’ → ‘${r.canonical}’ 합치기를 되돌립니다.\n${r.restorable ? `${r.restorable.toLocaleString()}행이 원래 이름 ‘${r.variant}’ 로 돌아가요.` : "이름을 바꾼 기록이 남아 있지 않아 규칙만 지워요."}\n(data CSV 는 먼저 백업돼요)`)) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await (await fetch(`${BASE_URL}/api/title-merge/undo`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kind: r.kind, artist: r.artist, variant: r.variant, canonical: r.canonical }) })).json();
      if (res.error) setMessage(`실패: ${res.error}`);
      else setMessage(`되돌렸어요: ‘${res.canonical}’ → ‘${res.variant}’ (${res.restored_rows.toLocaleString()}행 복원${res.backup ? ` · 백업 ${res.backup}` : ""})`);
      loadRules();
      if (artist.trim()) loadTitles(artist.trim());
    } catch (e) {
      setMessage(`실패: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const color = CAT[kind].main;
  const selectStyle = { padding: "0.45rem 0.6rem", width: "100%", boxSizing: "border-box" as const };
  return (
    <>
      <h2 style={{ marginTop: 0, borderLeft: `4px solid ${color}`, paddingLeft: "0.6rem" }}>{NOUN[kind]} 병합</h2>
      <p style={{ color: "#999", fontSize: "0.9rem", marginTop: 0 }}>
        같은 {NOUN[kind]}인데 제목이 다르게 적힌 항목(예: Romance / 로맨스)을 한 아티스트 안에서 하나로 합쳐요. 아티스트 이름이 서로 다르게 나뉘어 있으면 먼저 “아티스트 병합”으로 합치세요.
        통일 표기는 Last.fm 표기(Last.fm 행이 많은 쪽)를 기본으로 골라 두고, 합치면 규칙이 저장돼서 새로고침 때 같은 제목의 새 기록도 자동으로 합쳐집니다.
      </p>

      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", margin: "1rem 0" }}>
        <ArtistPicker label="아티스트" value={artist} onChange={setArtist} />
      </div>
      {artist.trim() && titles.length === 0 && <p style={{ color: "#999", fontSize: "0.9rem" }}>이 아티스트의 {NOUN[kind]} 기록이 없어요. 목록에서 아티스트를 골라 보세요.</p>}
      {titles.length === 1 && <p style={{ color: "#999", fontSize: "0.9rem" }}>{NOUN[kind]} 표기가 하나뿐이라 합칠 게 없어요.</p>}

      {titles.length >= 2 && (
        <div style={{ border: "1px solid rgba(128,128,128,0.3)", borderRadius: 10, padding: "1rem 1.2rem", marginBottom: "1rem" }}>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            <div style={{ flex: "1 1 280px" }}>
              <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "#999", marginBottom: 4 }}>합칠 {NOUN[kind]} (이 이름이 사라짐)</div>
              <select value={variant} onChange={(e) => setVariant(e.target.value)} style={selectStyle}>
                {titles.map((t) => (
                  <option key={t.title} value={t.title}>{label(t)}</option>
                ))}
              </select>
            </div>
            <div style={{ flex: "1 1 280px" }}>
              <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "#999", marginBottom: 4 }}>통일 표기 (남는 이름)</div>
              <select value={canonical} onChange={(e) => setCanonical(e.target.value)} style={selectStyle}>
                {titles.map((t) => (
                  <option key={t.title} value={t.title}>{label(t)}</option>
                ))}
              </select>
            </div>
          </div>
          {prev && (
            <>
              <div style={{ fontSize: "0.9rem", lineHeight: 1.7, marginTop: "0.8rem" }}>
                <div><b>{canonical}</b> <span style={{ color: "#999" }}>(남음)</span> — {src(prev.canonical)}</div>
                <div><b>{variant}</b> <span style={{ color: "#999" }}>(위로 합쳐짐)</span> — {src(prev.variant)}</div>
              </div>
              {prev.suggest_swap && !prev.error && (
                <p style={{ color: "#e0a800", fontSize: "0.85rem", margin: "0.7rem 0 0" }}>
                  ⚠️ ‘{variant}’ 쪽에 Last.fm 기록이 더 많아요. Last.fm 표기를 기준으로 삼으려면 ‘{variant}’ 을 통일 표기로 고르세요.
                </p>
              )}
              {prev.error && <p style={{ color: "#d66", margin: "0.7rem 0 0" }}>{prev.error}</p>}
              <div style={{ marginTop: "0.9rem" }}>
                <button onClick={merge} disabled={busy || !!prev.error} style={{ padding: "0.5rem 1.2rem", fontWeight: 700 }}>
                  {busy ? "합치는 중..." : "합치기"}
                </button>
              </div>
            </>
          )}
        </div>
      )}
      {message && <p style={{ margin: "0.5rem 0" }}>{message}</p>}

      {rules.length > 0 && (
        <>
          <h3 style={{ fontWeight: 400, marginTop: "2rem" }}>직접 합친 {NOUN[kind]} 목록</h3>
          <div style={{ fontSize: "0.9rem" }}>
            {rules.map((r) => (
              <div key={`${r.artist}|${r.variant}`} style={{ padding: "0.4rem 0.25rem", borderBottom: "1px solid rgba(128,128,128,0.25)", display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
                <span>
                  <span style={{ color: "#999" }}>{r.artist} · </span>
                  {r.variant} → <b>{r.canonical}</b>
                </span>
                <span style={{ marginLeft: "auto", color: "#999", fontSize: "0.8rem", alignSelf: "center" }}>
                  {r.pending ? "아직 변형 이름 기록이 남아 있어요 (다음 새로고침 때 합쳐짐)" : `반영됨${r.restorable ? ` · ${r.restorable.toLocaleString()}행` : ""}`}
                </span>
                <button onClick={() => undo(r)} disabled={busy} style={{ padding: "0.2rem 0.8rem", fontSize: "0.85rem" }}>
                  되돌리기
                </button>
              </div>
            ))}
          </div>
        </>
      )}
    </>
  );
}
