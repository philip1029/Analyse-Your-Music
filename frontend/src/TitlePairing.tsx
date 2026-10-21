import { useCallback, useEffect, useState } from "react";
import { BASE_URL } from "./config";

// 짝짓기 화면: 한 아티스트의 "Apple 쪽에만 있는" 앨범/곡 제목마다 Last.fm 쪽 제목을 골라 한꺼번에 합친다.
// 곡은 앨범 하나를 고른 뒤 그 앨범 안에서, 앨범은 아티스트 안에서 짝짓는다. 곡 길이가 ±2초로 일치하고 양쪽에서 유일하면 미리 채워 두고, 나머지는 비워 둔다.

export type PairKind = "album" | "track";
type Side = { title: string; A: number; L?: number; duration?: number | null; suggestion?: { title: string; reason: string } | null };
type Pairing = { artist: string; album?: string; left: Side[]; right: Side[] };
type AlbumRow = { album: string; a_only: number; l_only: number; plays: number };
type Bulk = { applied_pairs?: number; applied_rows?: number; backup?: string | null; skipped?: { variant: string; canonical: string; reason: string }[]; error?: string };

const NOUN: Record<PairKind, string> = { album: "앨범", track: "곡" };
const dur = (s?: number | null) => (s ? ` · ${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}` : "");

export function TitlePairing({ kind, artist, onDone }: { kind: PairKind; artist: string; onDone: () => void }) {
  const [albums, setAlbums] = useState<AlbumRow[]>([]);          // 곡 짝짓기에서 고를 앨범 목록
  const [album, setAlbum] = useState("");
  const [data, setData] = useState<Pairing | null>(null);
  const [picks, setPicks] = useState<Record<string, string>>({});   // 왼쪽 제목 -> 오른쪽(남길) 제목
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [skipped, setSkipped] = useState<NonNullable<Bulk["skipped"]>>([]);

  const a = artist.trim();

  const loadAlbums = useCallback(() => {
    if (kind !== "track" || !a) return;
    fetch(`${BASE_URL}/api/title-merge/albums?artist=${encodeURIComponent(a)}`)
      .then((r) => r.json())
      .then((d) => {
        const list = (d.albums ?? []) as AlbumRow[];
        setAlbums(list);
        setAlbum((cur) => (list.some((x) => x.album === cur) ? cur : (list[0]?.album ?? "")));
      })
      .catch(() => {});
  }, [kind, a]);

  const loadPairing = useCallback(() => {
    if (!a || (kind === "track" && !album)) {
      setData(null);
      return;
    }
    const url = kind === "track" ? `${BASE_URL}/api/title-merge/album-pairing?artist=${encodeURIComponent(a)}&album=${encodeURIComponent(album)}` : `${BASE_URL}/api/title-merge/artist-albums?artist=${encodeURIComponent(a)}`;
    fetch(url)
      .then((r) => r.json())
      .then((d: Pairing) => {
        setData(d);
        // 추천(곡 길이 일치)만 미리 채운다
        const init: Record<string, string> = {};
        d.left.forEach((l) => l.suggestion && (init[l.title] = l.suggestion.title));
        setPicks(init);
      })
      .catch(() => {});
  }, [kind, a, album]);

  useEffect(() => {
    setMessage(null);
    setSkipped([]);
    setData(null);
    setAlbums([]);
    if (kind === "track") loadAlbums();
  }, [kind, a, loadAlbums]);
  useEffect(loadPairing, [loadPairing]);

  const chosen = data ? data.left.filter((l) => picks[l.title]) : [];

  const save = async () => {
    if (chosen.length === 0) return;
    if (!window.confirm(`${a} 의 ${NOUN[kind]} ${chosen.length}쌍을 합칩니다.\n${chosen.map((l) => `${l.title} → ${picks[l.title]}`).join("\n")}\n(data CSV 는 먼저 백업돼요)`)) return;
    setBusy(true);
    setMessage(null);
    try {
      const res: Bulk = await (
        await fetch(`${BASE_URL}/api/title-merge/bulk`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ kind, artist: a, pairs: chosen.map((l) => ({ variant: l.title, canonical: picks[l.title] })) }),
        })
      ).json();
      if (res.error) setMessage(`실패: ${res.error}`);
      else {
        setSkipped(res.skipped ?? []);
        setMessage(`${res.applied_pairs ?? 0}쌍을 합쳤어요 (${(res.applied_rows ?? 0).toLocaleString()}행${res.backup ? ` · 백업 ${res.backup}` : ""})${res.skipped?.length ? ` · 건너뛴 ${res.skipped.length}쌍` : ""}`);
        onDone();
        if (kind === "track") loadAlbums();
        loadPairing();
      }
    } catch (e) {
      setMessage(`실패: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  };

  if (!a) return <p style={{ color: "#999", fontSize: "0.9rem" }}>위에서 아티스트를 고르면 짝지을 {NOUN[kind]} 목록이 나와요.</p>;

  const noLeft = data && (data.left.length === 0 || data.right.length === 0);
  return (
    <>
      {kind === "track" && (
        <div style={{ margin: "0 0 1rem" }}>
          <div style={{ fontSize: "0.75rem", fontWeight: 700, color: "#999", marginBottom: 4 }}>앨범 고르기 (영문·한글 곡 제목이 섞여 있는 앨범)</div>
          {albums.length === 0 ? (
            <p style={{ color: "#999", fontSize: "0.9rem", margin: 0 }}>이 아티스트에는 짝지을 곡이 있는 앨범이 없어요. (앨범 이름이 서로 다르게 나뉘어 있다면 먼저 “앨범” 짝짓기로 합치세요.)</p>
          ) : (
            <select value={album} onChange={(e) => setAlbum(e.target.value)} style={{ padding: "0.45rem 0.6rem", width: "100%", maxWidth: 520 }}>
              {albums.map((x) => (
                <option key={x.album} value={x.album}>
                  {x.album} — Apple 쪽에만 {x.a_only}곡 · Last.fm 쪽에만 {x.l_only}곡
                </option>
              ))}
            </select>
          )}
        </div>
      )}

      {data && noLeft && <p style={{ color: "#999", fontSize: "0.9rem" }}>짝지을 {NOUN[kind]}이 없어요. (Apple 쪽에만 있는 {NOUN[kind]} {data.left.length}개 · Last.fm {NOUN[kind]} {data.right.length}개)</p>}

      {data && !noLeft && (
        <div style={{ border: "1px solid rgba(128,128,128,0.3)", borderRadius: 10, padding: "1rem 1.2rem", marginBottom: "1rem" }}>
          <p style={{ color: "#999", fontSize: "0.85rem", margin: "0 0 0.8rem" }}>
            Apple 쪽에만 있는 {NOUN[kind]}마다 같은 {NOUN[kind]}의 Last.fm 제목을 고르세요. 안 고른 줄은 그대로 둡니다.
            {kind === "track" ? " 곡 길이가 ±2초로 일치해서 확실한 짝은 미리 채워 뒀어요 (확인해 보세요)." : ""}
          </p>
          {data.left.map((l) => {
            const used = picks[l.title];
            return (
              <div key={l.title} style={{ display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap", padding: "0.45rem 0", borderBottom: "1px solid rgba(128,128,128,0.2)" }}>
                <div style={{ flex: "1 1 220px", minWidth: 0 }}>
                  <div style={{ fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{l.title}</div>
                  <div style={{ color: "#999", fontSize: "0.8rem" }}>
                    Apple {l.A.toLocaleString()}회{dur(l.duration)}
                  </div>
                </div>
                <span style={{ color: "#999" }}>→</span>
                <select
                  value={used ?? ""}
                  onChange={(e) => setPicks((p) => ({ ...p, [l.title]: e.target.value }))}
                  style={{ flex: "1 1 240px", padding: "0.4rem 0.5rem", minWidth: 0 }}
                >
                  <option value="">— 합치지 않음 —</option>
                  {data.right.map((r) => (
                    <option key={r.title} value={r.title}>
                      {r.title} (Last.fm {(r.L ?? 0).toLocaleString()}){dur(r.duration)}
                    </option>
                  ))}
                </select>
                {l.suggestion && used === l.suggestion.title && <span style={{ color: "#6a9bd8", fontSize: "0.75rem" }}>{l.suggestion.reason}</span>}
              </div>
            );
          })}
          <div style={{ marginTop: "0.9rem", display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap" }}>
            <button onClick={save} disabled={busy || chosen.length === 0} style={{ padding: "0.5rem 1.2rem", fontWeight: 700 }}>
              {busy ? "합치는 중..." : `고른 ${chosen.length}쌍 합치기`}
            </button>
            <span style={{ color: "#999", fontSize: "0.8rem" }}>Last.fm 표기가 남고, 규칙이 저장돼서 새로고침 때도 자동 적용돼요.</span>
          </div>
        </div>
      )}
      {message && <p style={{ margin: "0.5rem 0" }}>{message}</p>}
      {skipped.length > 0 && (
        <ul style={{ color: "#e0a800", fontSize: "0.85rem", margin: "0 0 1rem", paddingLeft: "1.2rem" }}>
          {skipped.map((s) => (
            <li key={`${s.variant}|${s.canonical}`}>
              ‘{s.variant}’ → ‘{s.canonical}’: {s.reason}
            </li>
          ))}
        </ul>
      )}
    </>
  );
}
