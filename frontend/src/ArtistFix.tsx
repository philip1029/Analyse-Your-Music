import { useCallback, useEffect, useId, useState } from "react";
import { BASE_URL } from "./config";
import { Num } from "./motion";
import { CAT } from "./theme";

// 아티스트가 비어 있는 기록을 직접 채우는 화면 (Library 의 "아티스트 누락").
// 이미 있는 아티스트와 표기만 다르면(대소문자·띄어쓰기·기호) 기존 표기로 자동 합쳐진다. 저장할 때마다 data CSV 를 백업하고 변경 기록을 남긴다.

type Suggestion = { artist: string; reasons: string[]; count: number };
type Group = { track: string; album: string; count: number; first: string; last: string; suggestions: Suggestion[] };
type Missing = { total_rows: number; total_groups: number; items: Group[] };
type Applied = { applied_rows: number; backup: string | null; details: { track: string; album: string; artist: string; merged: boolean; rows: number }[]; error?: string };

const keyOf = (g: { track: string; album: string }) => `${g.track}\u0000${g.album}`;

// 입력하면 라이브러리의 기존 아티스트를 자동완성으로 보여 준다 (선택한 기간과 상관없이 전체 기록에서 찾는다)
function ArtistInput({ value, onChange, onEnter }: { value: string; onChange: (v: string) => void; onEnter: () => void }) {
  const listId = useId();
  const [options, setOptions] = useState<string[]>([]);
  useEffect(() => {
    const q = value.trim();
    if (!q) {
      setOptions([]);
      return;
    }
    const ctrl = new AbortController();
    const timer = setTimeout(() => {
      fetch(`${BASE_URL}/api/search?q=${encodeURIComponent(q)}&limit=8`, { signal: ctrl.signal })
        .then((r) => r.json())
        .then((d) => setOptions(((d.artists ?? []) as { name: string }[]).map((a) => a.name)))
        .catch(() => {});
    }, 250);
    return () => {
      clearTimeout(timer);
      ctrl.abort();
    };
  }, [value]);
  return (
    <>
      <input
        list={listId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && onEnter()}
        placeholder="아티스트 이름 (기존 아티스트면 자동 합침)"
        style={{ padding: "0.35rem 0.6rem", minWidth: 220, flex: 1 }}
      />
      <datalist id={listId}>
        {options.map((o) => (
          <option key={o} value={o} />
        ))}
      </datalist>
    </>
  );
}

export function MissingArtists() {
  const [data, setData] = useState<Missing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(() => {
    fetch(`${BASE_URL}/api/artist-missing?limit=300`)
      .then((r) => r.json())
      .then((d) => (d.error ? setError(d.error) : setData(d as Missing)))
      .catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);

  const save = async (groups: Group[]) => {
    const assignments = groups.filter((g) => (drafts[keyOf(g)] ?? "").trim()).map((g) => ({ track: g.track, album: g.album, artist: drafts[keyOf(g)].trim() }));
    if (assignments.length === 0) return;
    setSaving(true);
    setMessage(null);
    try {
      const res: Applied = await (await fetch(`${BASE_URL}/api/artist-fill`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ assignments }) })).json();
      if (res.error) {
        setMessage(`실패: ${res.error}`);
      } else {
        const merged = res.details.filter((d) => d.merged).map((d) => `‘${d.track}’ → ${d.artist}`);
        setMessage(`${res.applied_rows}행에 적용했어요${merged.length ? ` · 기존 아티스트로 합침: ${merged.join(", ")}` : ""}${res.backup ? ` · 백업 ${res.backup}` : ""}`);
        setDrafts((prev) => {
          const next = { ...prev };
          assignments.forEach((a) => delete next[keyOf(a)]);
          return next;
        });
        load();
      }
    } catch (e) {
      setMessage(`실패: ${(e as Error).message}`);
    } finally {
      setSaving(false);
    }
  };

  const filled = data ? data.items.filter((g) => (drafts[keyOf(g)] ?? "").trim()) : [];

  return (
    <>
      <h2 style={{ marginTop: 0, borderLeft: `4px solid ${CAT.artist.main}`, paddingLeft: "0.6rem" }}>아티스트 누락 관리</h2>
      <p style={{ color: "#999", fontSize: "0.9rem", marginTop: 0 }}>
        아티스트가 비어 있는 기록을 곡·앨범 묶음별로 직접 채워요. 같은 앨범·같은 곡에서 이미 알려진 아티스트를 후보로 보여 주고, 이미 있는 아티스트와 표기만 다르면 기존 표기로 합쳐집니다.
        저장하면 data CSV 를 백업하고 변경 기록(data/artist_fill_log.csv)을 남겨요.
      </p>
      {error && <p style={{ color: "#d66" }}>{error}</p>}
      {message && <p style={{ margin: "0.5rem 0" }}>{message}</p>}
      {data && (
        <>
          <p style={{ fontSize: "0.9rem" }}>
            아티스트가 빈 기록 <b><Num value={data.total_rows} /></b>행 · <b>{data.total_groups}</b>개 곡/앨범 묶음
            {data.items.length < data.total_groups ? ` (많이 들은 ${data.items.length}개만 표시)` : ""}
          </p>
          {filled.length > 0 && (
            <div style={{ position: "sticky", top: 0, zIndex: 5, background: "Canvas", padding: "0.5rem 0", borderBottom: "1px solid rgba(128,128,128,0.25)", marginBottom: "0.5rem" }}>
              <button onClick={() => save(filled)} disabled={saving} style={{ padding: "0.45rem 1rem", fontWeight: 700 }}>
                {saving ? "저장 중..." : `입력한 ${filled.length}개 묶음 한꺼번에 저장`}
              </button>
            </div>
          )}
          {data.items.length === 0 && <p style={{ color: "#999" }}>아티스트가 빈 기록이 없어요.</p>}
          {data.items.map((g) => {
            const k = keyOf(g);
            const draft = drafts[k] ?? "";
            return (
              <div key={k} style={{ padding: "0.7rem 0.25rem", borderBottom: "1px solid rgba(128,128,128,0.25)" }}>
                <div style={{ display: "flex", alignItems: "baseline", gap: "0.6rem", flexWrap: "wrap" }}>
                  <span style={{ fontWeight: 700 }}>{g.track}</span>
                  <span style={{ color: "#999", fontSize: "0.85rem" }}>{g.album || "(앨범 없음)"}</span>
                  <span style={{ marginLeft: "auto", color: "#999", fontSize: "0.8rem" }}>
                    {g.count.toLocaleString()}회 · {g.first.slice(0, 10)}{g.last.slice(0, 10) !== g.first.slice(0, 10) ? ` ~ ${g.last.slice(0, 10)}` : ""}
                  </span>
                </div>
                {g.suggestions.length > 0 && (
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 6, alignItems: "center" }}>
                    <span style={{ color: "#999", fontSize: "0.75rem" }}>후보</span>
                    {g.suggestions.map((s) => (
                      <button
                        key={s.artist}
                        onClick={() => setDrafts((p) => ({ ...p, [k]: s.artist }))}
                        title={`${s.reasons.join(" · ")} (${s.count.toLocaleString()}회)`}
                        style={{ padding: "0.1rem 0.6rem", borderRadius: 999, fontSize: "0.8rem", background: CAT.artist.soft, border: draft === s.artist ? `2px solid ${CAT.artist.main}` : "1px solid transparent", cursor: "pointer" }}
                      >
                        {s.artist} <span style={{ color: "#999" }}>· {s.reasons.join("/")}</span>
                      </button>
                    ))}
                  </div>
                )}
                <div style={{ display: "flex", gap: "0.5rem", marginTop: 8, flexWrap: "wrap" }}>
                  <ArtistInput value={draft} onChange={(v) => setDrafts((p) => ({ ...p, [k]: v }))} onEnter={() => save([g])} />
                  <button onClick={() => save([g])} disabled={saving || !draft.trim()} style={{ padding: "0.3rem 0.9rem" }}>
                    저장
                  </button>
                </div>
              </div>
            );
          })}
        </>
      )}
    </>
  );
}
