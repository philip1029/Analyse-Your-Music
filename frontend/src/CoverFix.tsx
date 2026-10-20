import { useCallback, useEffect, useRef, useState } from "react";
import { BASE_URL } from "./config";
import { Cover, absoluteCoverUrl, coverPath, invalidateCover } from "./Cover";

// 자동으로 못 찾은 앨범 커버·아티스트 사진을 사용자가 직접 채우는 화면.
//  - CoverEditor: 이미지를 붙여넣기(Cmd/Ctrl+V) / 끌어다 놓기 / 파일 선택으로 지정하고, 자동 조회로 되돌릴 수 있다.
//  - MissingCovers: 많이 들은 앨범 중 커버가 없는 목록 (Library 의 "커버 누락" 화면).

const MAX_SIDE = 800;

// 브라우저에서 줄여서(긴 변 800px, JPEG) data URL 로 만든다. 서버가 다시 한 번 검증한다.
async function prepareImage(blob: Blob): Promise<string> {
  const url = URL.createObjectURL(blob);
  try {
    const img = await new Promise<HTMLImageElement>((resolve, reject) => {
      const i = new Image();
      i.onload = () => resolve(i);
      i.onerror = () => reject(new Error("이미지를 읽을 수 없어요. PNG/JPEG/WEBP 파일인지 확인해 주세요."));
      i.src = url;
    });
    const scale = Math.min(1, MAX_SIDE / Math.max(img.width, img.height));
    const canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(img.width * scale));
    canvas.height = Math.max(1, Math.round(img.height * scale));
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("이미지를 처리할 수 없어요.");
    ctx.fillStyle = "#fff";                                   // 투명 PNG 는 흰 배경으로
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
    return canvas.toDataURL("image/jpeg", 0.9);
  } finally {
    URL.revokeObjectURL(url);
  }
}

export type CoverTarget = { kind: "album" | "artist"; artist: string; album?: string; label: string };

export function CoverEditor({ target, onClose, onSaved }: { target: CoverTarget; onClose: () => void; onSaved: () => void }) {
  const [preview, setPreview] = useState<string | null>(null);
  const [current, setCurrent] = useState<{ url: string | null; source?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  const loadCurrent = useCallback(() => {
    const path = coverPath(target.kind, target.artist, target.album);
    if (!path) return;
    fetch(`${BASE_URL}${path}`)
      .then((r) => r.json())
      .then(setCurrent)
      .catch(() => setCurrent({ url: null }));
  }, [target]);

  useEffect(loadCurrent, [loadCurrent]);

  const take = useCallback(async (blob: Blob | null | undefined) => {
    if (!blob) return;
    setError(null);
    try {
      setPreview(await prepareImage(blob));
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  // 붙여넣기 (이미지를 복사한 뒤 Cmd/Ctrl+V) 와 ESC
  useEffect(() => {
    const onPaste = (e: ClipboardEvent) => {
      const item = [...(e.clipboardData?.items ?? [])].find((i) => i.type.startsWith("image/"));
      if (item) {
        e.preventDefault();
        take(item.getAsFile());
      }
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("paste", onPaste);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("paste", onPaste);
      window.removeEventListener("keydown", onKey);
    };
  }, [take, onClose]);

  const save = async () => {
    if (!preview) return;
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${BASE_URL}/api/cover-override`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ kind: target.kind, artist: target.artist, album: target.album ?? "", image: preview }),
      });
      if (!res.ok) throw new Error((await res.text()) || "저장하지 못했어요.");
      invalidateCover(target.kind, target.artist, target.album);
      onSaved();
      onClose();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const reset = async () => {
    setBusy(true);
    try {
      const q = new URLSearchParams({ kind: target.kind, artist: target.artist, album: target.album ?? "" });
      await fetch(`${BASE_URL}/api/cover-override?${q}`, { method: "DELETE" });
      invalidateCover(target.kind, target.artist, target.album);
      onSaved();
      onClose();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  };

  const round = target.kind === "artist";
  const shown = preview ?? (current?.url ? absoluteCoverUrl(current.url) : null);
  return (
    <div
      onClick={(e) => e.target === e.currentTarget && onClose()}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.72)", zIndex: 1100, display: "flex", justifyContent: "center", alignItems: "flex-start", overflowY: "auto", padding: "40px 12px" }}
    >
      <div role="dialog" aria-label="커버 직접 지정" style={{ background: "#1c1d23", color: "#eee", borderRadius: 12, padding: "1rem 1.2rem 1.3rem", width: "min(100%, 480px)", boxShadow: "0 8px 40px rgba(0,0,0,0.6)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h3 style={{ margin: 0 }}>{round ? "아티스트 사진" : "앨범 커버"} 직접 지정</h3>
          <button onClick={onClose} style={{ padding: "0.3rem 0.7rem" }}>
            ✕ 닫기
          </button>
        </div>
        <p style={{ margin: "0.6rem 0 0.2rem", fontWeight: 700 }}>{target.label}</p>
        <p style={{ margin: 0, color: "#999", fontSize: "0.85rem" }}>
          {current?.source === "manual" ? "지금은 직접 지정한 이미지를 쓰고 있어요." : current?.url ? "지금은 자동으로 찾은 이미지를 쓰고 있어요." : "지금은 이미지가 없어요."}
        </p>

        <div
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragging(false);
            take(e.dataTransfer.files?.[0]);
          }}
          onClick={() => fileRef.current?.click()}
          style={{
            marginTop: "1rem",
            border: `2px dashed ${dragging ? "#8884d8" : "#666"}`,
            borderRadius: 10,
            padding: "1rem",
            textAlign: "center",
            cursor: "pointer",
            background: dragging ? "rgba(136,132,216,0.12)" : "transparent",
          }}
        >
          <div style={{ width: 200, height: 200, margin: "0 auto 0.8rem", borderRadius: round ? "50%" : 8, overflow: "hidden", background: "#2a2a30", display: "flex", alignItems: "center", justifyContent: "center" }}>
            {shown ? <img src={shown} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <span style={{ color: "#777" }}>이미지 없음</span>}
          </div>
          <div style={{ fontWeight: 700 }}>이미지를 붙여넣거나(Cmd/Ctrl + V), 끌어다 놓거나, 눌러서 파일을 고르세요</div>
          <div style={{ color: "#999", fontSize: "0.8rem", marginTop: 4 }}>웹에서 찾은 이미지는 우클릭 → "이미지 복사"한 뒤 이 창에서 붙여넣으면 돼요. PNG·JPEG·WEBP, 8MB 이하.</div>
          <input ref={fileRef} type="file" accept="image/png,image/jpeg,image/webp" style={{ display: "none" }} onChange={(e) => take(e.target.files?.[0])} />
        </div>

        {preview && <p style={{ color: "#8884d8", fontSize: "0.85rem", margin: "0.6rem 0 0" }}>새 이미지가 준비됐어요. 저장하면 이 이미지로 바뀝니다.</p>}
        {error && <p style={{ color: "#d66", margin: "0.6rem 0 0" }}>{error}</p>}

        <div style={{ display: "flex", gap: "0.6rem", justifyContent: "flex-end", marginTop: "1rem", flexWrap: "wrap" }}>
          {current?.source === "manual" && (
            <button onClick={reset} disabled={busy} style={{ padding: "0.5rem 0.9rem", marginRight: "auto" }}>
              자동 조회로 되돌리기
            </button>
          )}
          <button onClick={save} disabled={!preview || busy} style={{ padding: "0.5rem 1.2rem", fontWeight: 700 }}>
            {busy ? "저장 중..." : "저장"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- 커버 누락 목록

type Audit = { top: number; found: number; manual: number; unchecked: number; missing: { name: string; artist: string | null; count: number; reason: string }[] };

export function MissingCovers() {
  const [data, setData] = useState<Audit | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [editing, setEditing] = useState<CoverTarget | null>(null);
  const [version, setVersion] = useState(0);

  const load = useCallback(() => {
    fetch(`${BASE_URL}/api/cover-missing?top=300`)
      .then((r) => r.json())
      .then((d) => (d.error ? setError(d.error) : setData(d as Audit)))
      .catch((e) => setError(e.message));
  }, []);

  useEffect(load, [load, version]);

  // 아직 조회하지 않은 앨범을 30개씩 Last.fm 에서 확인한다 (곡당 0.5초쯤 걸려서 한 번에 조금씩)
  const check = async () => {
    setChecking(true);
    setError(null);
    try {
      const d = await (await fetch(`${BASE_URL}/api/cover-check?limit=30`, { method: "POST" })).json();
      if (d.error) setError(d.error);
      load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setChecking(false);
    }
  };

  return (
    <>
      <h2 style={{ marginTop: 0 }}>커버 누락 관리</h2>
      <p style={{ color: "#999", fontSize: "0.9rem", marginTop: 0 }}>
        많이 들은 앨범 중 커버를 자동으로 못 찾은 것들이에요. 이미지를 직접 지정하면 앱 전체(목록·페이지·공유 이미지)에 쓰입니다.
      </p>
      {error && <p style={{ color: "#d66" }}>{error}</p>}
      {!data && !error && <p style={{ color: "#999" }}>불러오는 중...</p>}
      {data && (
        <>
          <p style={{ fontSize: "0.9rem" }}>
            상위 {data.top}개 중 · 커버 있음 <b>{data.found}</b> · 직접 지정 <b>{data.manual}</b> · 누락 <b>{data.missing.length}</b> · 아직 확인 안 함 <b>{data.unchecked}</b>
          </p>
          {data.unchecked > 0 && (
            <div style={{ marginBottom: "1rem" }}>
              <button onClick={check} disabled={checking} style={{ padding: "0.4rem 1rem" }}>
                {checking ? "확인 중... (30개, 약 15초)" : `확인 안 한 앨범 ${Math.min(30, data.unchecked)}개 확인하기`}
              </button>
            </div>
          )}
          {data.missing.length === 0 && <p style={{ color: "#999" }}>누락된 앨범이 없어요. {data.unchecked > 0 ? "위 버튼으로 나머지를 확인해 보세요." : ""}</p>}
          {data.missing.map((m) => (
            <div key={`${m.artist}|${m.name}`} style={{ display: "flex", alignItems: "center", gap: "0.9rem", padding: "0.55rem 0.25rem", borderBottom: "1px solid rgba(128,128,128,0.25)" }}>
              <Cover key={version} kind="album" artist={m.artist} album={m.name} size={44} />
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{m.name}</div>
                <div style={{ color: "#999", fontSize: "0.85rem" }}>
                  {m.artist ?? "(아티스트 없음)"} · {m.count.toLocaleString()}회 · {m.reason}
                </div>
              </div>
              {m.artist ? (
                <button onClick={() => setEditing({ kind: "album", artist: m.artist as string, album: m.name, label: `${m.name} — ${m.artist}` })} style={{ padding: "0.3rem 0.8rem" }}>
                  이미지 추가
                </button>
              ) : (
                <span style={{ color: "#777", fontSize: "0.8rem" }}>아티스트가 있어야 추가할 수 있어요</span>
              )}
            </div>
          ))}
        </>
      )}
      {editing && <CoverEditor target={editing} onClose={() => setEditing(null)} onSaved={() => setVersion((v) => v + 1)} />}
    </>
  );
}
