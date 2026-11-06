import { useCallback, useEffect, useState } from "react";
import { BASE_URL } from "./config";
import { Cover } from "./Cover";
import type { LibraryTarget } from "./Library";

// Overview 의 "오늘의 추천 앨범": 서버가 규칙으로 고른 앨범을 세 가지 기준(다시 들어볼 / 한 번만 들은 / 도전)으로 보여 준다.
// 날짜가 같으면 같은 추천이고, "다시 뽑기"는 salt 를 올려 다른 후보를 받는다. 누르면 Library 의 앨범 페이지로 간다.

type Pick = { name: string; artist: string | null; plays: number; days: number; tracks: number; first_played: string; last_played: string; days_since: number; reason: string };
type Category = { id: string; label: string; hint: string; total: number; picks: Pick[] };
type Result = { date: string; ref: string | null; categories: Category[]; error?: string };

const ICON: Record<string, string> = { dormant: "🕰️", once: "1️⃣", challenge: "🎯" };

export function RecommendCard({ onOpen }: { onOpen: (t: LibraryTarget) => void }) {
  const [salt, setSalt] = useState(0);
  const [data, setData] = useState<Result | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${BASE_URL}/api/recommend?salt=${salt}`)
      .then((r) => r.json())
      .then((d: Result) => !cancelled && (d.error ? setError(d.error) : (setError(null), setData(d))))
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [salt]);

  const reroll = useCallback(() => setSalt((s) => s + 1), []);
  if (error && !data) return null;                                   // 추천은 부가 기능이라 실패해도 화면을 막지 않는다
  if (!data || data.categories.every((c) => c.picks.length === 0)) return null;
  return (
    <div className="aym-panel" style={{ margin: "1.6rem 0 0", padding: "16px 20px" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "0.8rem", marginBottom: "0.9rem" }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ color: "var(--scrobble)", fontSize: "0.75rem", fontWeight: 700, letterSpacing: "0.06em" }}>TODAY'S PICKS</div>
          <div style={{ fontSize: "1.1rem", fontWeight: 700 }}>
            오늘의 추천 앨범 <span style={{ color: "#999", fontSize: "0.8rem", fontWeight: 400 }}>{data.date}</span>
          </div>
        </div>
        <button type="button" onClick={reroll} title="다른 앨범으로 다시 뽑기" aria-label="다시 뽑기" style={{ flexShrink: 0, display: "inline-flex", alignItems: "center", gap: 6 }}>
          <span aria-hidden>🎲</span> 다시 뽑기
        </button>
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: "1.2rem" }}>
        {data.categories
          .filter((c) => c.picks.length > 0)
          .map((c) => (
            <section key={c.id} aria-label={c.label}>
              <h3 title={c.hint} style={{ margin: "0 0 0.1rem", fontSize: "0.95rem" }}>
                <span aria-hidden>{ICON[c.id] ?? "💿"}</span> {c.label}
              </h3>
              <div style={{ color: "#999", fontSize: "0.78rem", marginBottom: "0.4rem" }}>
                {c.hint} · 후보 {c.total.toLocaleString()}개
              </div>
              {c.picks.map((p) => (
                <div
                  key={`${p.artist}|${p.name}`}
                  role="button"
                  tabIndex={0}
                  onClick={() => onOpen({ kind: "album", name: p.name, artist: p.artist })}
                  onKeyDown={(e) => e.key === "Enter" && onOpen({ kind: "album", name: p.name, artist: p.artist })}
                  style={{ display: "flex", gap: "0.7rem", padding: "0.5rem 0.25rem", borderTop: "1px solid rgba(128,128,128,0.25)", cursor: "pointer", alignItems: "flex-start", textAlign: "left" }}
                >
                  <Cover kind="album" artist={p.artist} album={p.name} size={56} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.name}</div>
                    {p.artist && <div style={{ color: "#999", fontSize: "0.85rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{p.artist}</div>}
                    <div style={{ fontSize: "0.8rem", marginTop: 2, lineHeight: 1.4 }}>{p.reason}</div>
                  </div>
                </div>
              ))}
            </section>
          ))}
      </div>
    </div>
  );
}
