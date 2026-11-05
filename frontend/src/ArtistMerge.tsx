import { useCallback, useEffect, useState } from "react";
import { BASE_URL } from "./config";
import { Cover } from "./Cover";
import { CAT, catPill } from "./theme";

// 같은 사람인데 이름이 다른 아티스트(예: 검정치마 / The Black Skirts)를 하나로 합치거나, 아티스트 이름을 다른 이름으로 바꾸는 화면 (Library 의 "아티스트 병합").
// "이름 바꾸기"는 같은 규칙·백업·되돌리기 장치를 쓰되, 바꿀 이름이 기록에 없는 새 이름이어도 된다 (합치기는 오타를 막으려고 기록에 있는 이름만 받는다).
// 통일 이름은 Last.fm 이 쓰는 표기(L 행이 많은 쪽)를 권한다. 합치면 data CSV 를 백업하고 변경 기록을 남기며,
// 규칙(config/artist_merge.txt)이 남아서 이후 새로고침 때 같은 이름의 새 기록도 자동으로 합쳐진다.

type Stats = { name: string; A: number; L: number; total: number };
type Preview = { variant: Stats; canonical: Stats; suggest_swap: boolean; collisions: number; error: string | null; rename?: boolean };
type Rule = { variant: string; canonical: string; pending: boolean; restorable: number };

// 이름 입력 + 기존 아티스트 자동완성 (선택한 기간과 상관없이 전체 기록에서 찾는다)
export function ArtistPicker({ label, value, onChange }: { label: string; value: string; onChange: (v: string) => void }) {
  const [hits, setHits] = useState<{ name: string; count: number }[]>([]);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const q = value.trim();
    if (!q) {
      setHits([]);
      return;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      fetch(`${BASE_URL}/api/search?q=${encodeURIComponent(q)}&limit=6`, { signal: ctrl.signal })
        .then((r) => r.json())
        .then((d) => setHits((d.artists ?? []) as { name: string; count: number }[]))
        .catch(() => {});
    }, 250);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [value]);
  return (
    <div style={{ position: "relative", flex: "1 1 260px" }}>
      <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "#999", marginBottom: 4 }}>{label}</div>
      <input
        value={value}
        onChange={(e) => {
          onChange(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder="아티스트 이름 검색"
        style={{ width: "100%", boxSizing: "border-box", padding: "0.5rem 0.7rem" }}
      />
      {open && hits.length > 0 && !hits.some((h) => h.name === value) && (
        <div style={{ position: "absolute", top: "100%", left: 0, right: 0, zIndex: 10, background: "Canvas", color: "CanvasText", border: "1px solid rgba(128,128,128,0.4)", borderRadius: 8, boxShadow: "0 8px 24px rgba(0,0,0,0.35)", marginTop: 2 }}>
          {hits.map((h) => (
            <div
              key={h.name}
              onMouseDown={() => {
                onChange(h.name);
                setOpen(false);
              }}
              style={{ display: "flex", alignItems: "center", gap: "0.6rem", padding: "0.35rem 0.7rem", cursor: "pointer" }}
            >
              <Cover kind="artist" artist={h.name} size={28} />
              <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{h.name}</span>
              <span style={{ color: "#999", fontSize: "0.8rem" }}>{h.count.toLocaleString()}회</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

const src = (s: Stats) => `${s.total.toLocaleString()}행 (Apple ${s.A.toLocaleString()} · Last.fm ${s.L.toLocaleString()})`;

export function MergeArtists({ onPair }: { onPair?: (artist: string) => void }) {
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [keepFirst, setKeepFirst] = useState(false);      // true: 첫 번째 이름이 통일 이름
  const [touched, setTouched] = useState(false);            // 사용자가 방향을 직접 골랐으면 자동 제안을 하지 않는다
  const [prev, setPrev] = useState<Preview | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [rules, setRules] = useState<Rule[]>([]);
  const [justMerged, setJustMerged] = useState<string | null>(null);   // 방금 합친 아티스트(통일 이름): 앨범·곡 짝짓기로 이어 가기
  const [mode, setMode] = useState<"merge" | "rename">("merge");
  const [newName, setNewName] = useState("");                          // 이름 바꾸기: 새 이름 (바꿀 아티스트는 a)
  const [renPrev, setRenPrev] = useState<Preview | null>(null);

  const loadRules = useCallback(() => {
    fetch(`${BASE_URL}/api/artist-merge/rules`)
      .then((r) => r.json())
      .then((d) => setRules(d.rules ?? []))
      .catch(() => {});
  }, []);
  useEffect(loadRules, [loadRules]);

  // 이름 바꾸기: 바꿀 아티스트와 새 이름이 정해질 때마다 미리보기 (새 이름이 기록에 없어도 된다)
  useEffect(() => {
    if (mode !== "rename" || !a.trim() || !newName.trim()) {
      setRenPrev(null);
      return;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      fetch(`${BASE_URL}/api/artist-merge/preview?variant=${encodeURIComponent(a)}&canonical=${encodeURIComponent(newName)}&rename=true`, { signal: ctrl.signal })
        .then((r) => r.json())
        .then((d) => setRenPrev(d.error && !d.variant ? null : (d as Preview)))
        .catch(() => {});
    }, 250);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [mode, a, newName]);

  const rename = async () => {
    if (!renPrev || renPrev.error) return;
    const joins = !renPrev.rename;      // 이미 기록에 있는 이름이면 이름 바꾸기가 곧 합치기
    if (!window.confirm(`‘${a}’ 의 기록 ${renPrev.variant.total.toLocaleString()}행의 이름을 ‘${newName.trim()}’ 로 ${joins ? `바꾸며 기존 ‘${newName.trim()}’ 기록과 합칩니다` : "바꿉니다"}.\n(data CSV 는 먼저 백업되고, 아래 목록의 “되돌리기”로 원래 이름으로 돌릴 수 있어요)`)) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await (await fetch(`${BASE_URL}/api/artist-merge`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ variant: a, canonical: newName, rename: true }) })).json();
      if (res.error) setMessage(`실패: ${res.error}`);
      else {
        setMessage(`${res.rename ? "이름을 바꿨어요" : "합쳤어요"}: ‘${res.variant}’ → ‘${res.canonical}’ (${res.applied_rows.toLocaleString()}행${res.backup ? ` · 백업 ${res.backup}` : ""})`);
        if (!res.rename) setJustMerged(res.canonical);
        setA("");
        setNewName("");
        setRenPrev(null);
        loadRules();
      }
    } catch (e) {
      setMessage(`실패: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  // 두 이름이 정해질 때마다 미리보기를 받고, 통일 이름은 Last.fm 표기(L 행이 많은 쪽)로 자동 제안한다
  const variantName = keepFirst ? b : a;
  const canonicalName = keepFirst ? a : b;
  useEffect(() => {
    if (!a.trim() || !b.trim()) {
      setPrev(null);
      return;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      fetch(`${BASE_URL}/api/artist-merge/preview?variant=${encodeURIComponent(variantName)}&canonical=${encodeURIComponent(canonicalName)}`, { signal: ctrl.signal })
        .then((r) => r.json())
        .then((d) => {
          const p = d.error && !d.variant ? null : (d as Preview);
          setPrev(p);
          if (p?.suggest_swap && !touched) setKeepFirst((k) => !k);   // Last.fm 기록이 더 많은 쪽을 통일 이름으로
        })
        .catch(() => {});
    }, 250);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [a, b, variantName, canonicalName, touched]);

  const undo = async (r: Rule) => {
    const rows = r.restorable;
    if (!window.confirm(`‘${r.variant}’ → ‘${r.canonical}’ 합치기를 되돌립니다.\n${rows ? `${rows.toLocaleString()}행이 원래 이름 ‘${r.variant}’ 로 돌아가요.` : "이름을 바꾼 기록이 남아 있지 않아 규칙만 지워요."}\n(data CSV 는 먼저 백업돼요)`)) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await (await fetch(`${BASE_URL}/api/artist-merge/undo`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ variant: r.variant, canonical: r.canonical }) })).json();
      if (res.error) setMessage(`실패: ${res.error}`);
      else setMessage(`되돌렸어요: ‘${res.canonical}’ → ‘${res.variant}’ (${res.restored_rows.toLocaleString()}행 복원${res.backup ? ` · 백업 ${res.backup}` : ""})`);
      loadRules();
    } catch (e) {
      setMessage(`실패: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  const merge = async () => {
    if (!prev || prev.error) return;
    if (!window.confirm(`‘${variantName}’ 의 기록 ${prev.variant.total.toLocaleString()}행을 ‘${canonicalName}’ 로 합칩니다.\n(data CSV 는 먼저 백업돼요)`)) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await (await fetch(`${BASE_URL}/api/artist-merge`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ variant: variantName, canonical: canonicalName }) })).json();
      if (res.error) setMessage(`실패: ${res.error}`);
      else {
        setMessage(`합쳤어요: ‘${res.variant}’ → ‘${res.canonical}’ (${res.applied_rows.toLocaleString()}행${res.backup ? ` · 백업 ${res.backup}` : ""})`);
        setJustMerged(res.canonical);
        setA("");
        setB("");
        setPrev(null);
        loadRules();
      }
    } catch (e) {
      setMessage(`실패: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <h2 style={{ marginTop: 0 }}>아티스트 병합 · 이름 바꾸기</h2>
      <div className="aym-seg" role="group" aria-label="작업 종류" style={{ margin: "0.2rem 0 0.9rem" }}>
        <button aria-pressed={mode === "merge"} onClick={() => setMode("merge")}>합치기</button>
        <button aria-pressed={mode === "rename"} onClick={() => setMode("rename")}>이름 바꾸기</button>
      </div>
      {mode === "merge" ? (
        <p style={{ color: "var(--text-3)", fontSize: "0.9rem", marginTop: 0 }}>
          같은 사람인데 이름이 다른 아티스트(예: 검정치마 / The Black Skirts)를 하나로 합쳐요. 합치면 두 이름의 모든 기록이 통일 이름으로 바뀌고, 규칙이 저장돼서
          이후 새로고침 때 같은 이름의 새 기록도 자동으로 합쳐집니다. 합치기 전에 data CSV 를 백업하고 변경 기록(data/artist_normalize_log.csv)을 남겨요.
        </p>
      ) : (
        <p style={{ color: "var(--text-3)", fontSize: "0.9rem", marginTop: 0 }}>
          아티스트의 이름을 다른 이름으로 바꿔요 (예: THORNAPPLE → 쏜애플). <b style={{ color: "var(--text-2)" }}>새 이름이 기록에 없어도 돼요.</b> 그 아티스트의 모든 기록 이름이 바뀌고,
          규칙이 저장돼서 이후 새로고침 때 같은 옛 이름의 새 기록도 자동으로 새 이름이 됩니다. 사진·장르 태그는 새 이름으로 다시 찾아요. 바꾸기 전에 data CSV 를 백업하고, 아래 목록의 “되돌리기”로 원래 이름으로 돌릴 수 있어요.
        </p>
      )}

      {mode === "rename" ? (
        <>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "flex-end", margin: "1rem 0" }}>
            <ArtistPicker label="바꿀 아티스트" value={a} onChange={setA} />
            <div style={{ flex: "1 1 260px" }}>
              <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "var(--text-3)", marginBottom: 4 }}>새 이름</div>
              <input value={newName} onChange={(e) => setNewName(e.target.value)} onKeyDown={(e) => e.key === "Enter" && renPrev && !renPrev.error && !busy && rename()} placeholder="바꿀 새 이름" style={{ width: "100%", padding: "0.5rem 0.7rem" }} />
            </div>
          </div>
          {renPrev && (
            <div className="aym-panel" style={{ marginBottom: "1rem" }}>
              <div style={{ fontSize: "0.9rem", lineHeight: 1.7 }}>
                <div>
                  <b>{a}</b> <span style={{ color: "var(--text-3)" }}>→</span> <b>{newName.trim()}</b>
                </div>
                <div style={{ color: "var(--text-2)" }}>바뀌는 기록: {src(renPrev.variant)}</div>
                {!renPrev.error && (
                  <div style={{ color: renPrev.rename ? "var(--album)" : "#e0a800" }}>
                    {renPrev.rename ? "기록에 없는 새 이름이에요. 이름만 바뀌어요." : `이미 기록에 있는 이름이에요 (${src(renPrev.canonical)}). 두 이름이 합쳐져요.`}
                  </div>
                )}
              </div>
              {renPrev.error && <p style={{ color: "#e07070", margin: "0.7rem 0 0" }}>{renPrev.error}</p>}
              <div style={{ marginTop: "0.9rem" }}>
                <button onClick={rename} disabled={busy || !!renPrev.error} style={{ fontWeight: 700 }}>
                  {busy ? "바꾸는 중..." : renPrev.rename ? "이름 바꾸기" : "바꾸고 합치기"}
                </button>
              </div>
            </div>
          )}
        </>
      ) : (
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", alignItems: "flex-end", margin: "1rem 0" }}>
        <ArtistPicker label="아티스트 1" value={a} onChange={(v) => { setA(v); setTouched(false); }} />
        <ArtistPicker label="아티스트 2" value={b} onChange={(v) => { setB(v); setTouched(false); }} />
      </div>
      )}

      {mode === "merge" && prev && (
        <div className="aym-panel" style={{ marginBottom: "1rem" }}>
          <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "#999", marginBottom: 6 }}>통일 이름 (남는 이름)</div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.8rem" }}>
            {[
              { name: a, first: true },
              { name: b, first: false },
            ].map((o) => (
              <button
                key={o.name}
                onClick={() => {
                  setKeepFirst(o.first);
                  setTouched(true);
                }}
                style={catPill(keepFirst === o.first, CAT.artist.main)}
              >
                {o.name}
              </button>
            ))}
          </div>
          <div style={{ fontSize: "0.9rem", lineHeight: 1.7 }}>
            <div>
              <b>{canonicalName}</b> <span style={{ color: "#999" }}>(남음)</span> — {src(prev.canonical)}
            </div>
            <div>
              <b>{variantName}</b> <span style={{ color: "#999" }}>(이 이름이 사라지고 위로 합쳐짐)</span> — {src(prev.variant)}
            </div>
          </div>
          {prev.suggest_swap && !prev.error && (
            <p style={{ color: "#e0a800", fontSize: "0.85rem", margin: "0.7rem 0 0" }}>
              ⚠️ ‘{variantName}’ 쪽에 Last.fm 기록이 더 많아요. Last.fm 표기를 기준으로 삼으려면 위에서 ‘{variantName}’ 을 통일 이름으로 고르세요.
            </p>
          )}
          {prev.error && <p style={{ color: "#d66", margin: "0.7rem 0 0" }}>{prev.error}</p>}
          <div style={{ marginTop: "0.9rem" }}>
            <button onClick={merge} disabled={busy || !!prev.error} style={{ padding: "0.5rem 1.2rem", fontWeight: 700 }}>
              {busy ? "합치는 중..." : "합치기"}
            </button>
          </div>
        </div>
      )}
      {message && <p style={{ margin: "0.5rem 0" }}>{message}</p>}
      {justMerged && onPair && (
        <div style={{ margin: "0.5rem 0 1rem", padding: "0.8rem 1rem", border: `1px solid ${CAT.artist.main}`, borderRadius: 10 }}>
          <div style={{ fontSize: "0.9rem", marginBottom: "0.5rem" }}>
            ‘{justMerged}’ 의 앨범·곡 제목도 영문/한글로 나뉘어 있을 수 있어요. 이어서 짝지어 합치세요.
          </div>
          <button onClick={() => onPair(justMerged)} style={{ padding: "0.4rem 1rem", fontWeight: 700 }}>
            ‘{justMerged}’ 앨범·곡 짝짓기 →
          </button>
        </div>
      )}

      {rules.length > 0 && (
        <>
          <h3 style={{ marginTop: "2rem" }}>직접 합치거나 이름을 바꾼 목록</h3>
          <div style={{ fontSize: "0.9rem" }}>
            {rules.map((r) => (
              <div key={r.variant} style={{ padding: "0.4rem 0.25rem", borderBottom: "1px solid rgba(128,128,128,0.25)", display: "flex", gap: "0.6rem", flexWrap: "wrap" }}>
                <span>
                  {r.variant} → <b>{r.canonical}</b>
                </span>
                <span style={{ marginLeft: "auto", color: "#999", fontSize: "0.8rem", alignSelf: "center" }}>
                  {r.pending ? "아직 변형 이름 기록이 남아 있어요 (다음 새로고침 때 합쳐짐)" : `반영됨${r.restorable ? ` · ${r.restorable.toLocaleString()}행` : ""}`}
                </span>
                {onPair && (
                  <button onClick={() => onPair(r.canonical)} style={{ padding: "0.2rem 0.8rem", fontSize: "0.85rem" }}>
                    앨범·곡 짝짓기
                  </button>
                )}
                <button onClick={() => undo(r)} disabled={busy} style={{ padding: "0.2rem 0.8rem", fontSize: "0.85rem" }}>
                  되돌리기
                </button>
              </div>
            ))}
          </div>
          <p style={{ color: "#999", fontSize: "0.8rem" }}>“되돌리기”는 규칙을 지우고, 그때 이름이 바뀐 기록만 원래 이름으로 돌려놓아요 (CSV 는 먼저 백업돼요).</p>
        </>
      )}
    </>
  );
}
