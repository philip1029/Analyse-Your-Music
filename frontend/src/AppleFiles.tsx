import { useCallback, useEffect, useState } from "react";
import { BASE_URL } from "./config";

// Data 탭: Apple Music 파일 안내. 파일마다 용도 · 받는 곳 · 지금 폴더에 있는지를 보여 주고,
// 다른 위치에 받아 둔 파일(또는 그 파일이 든 폴더)을 경로로 알려 주면 설정한 Apple 폴더로 복사해 준다 (원본은 그대로).

type FileRow = { key: string; label: string; names: string[]; purpose: string; source: string; found: string | null; size: number | null };
type Status = { folder: string; files: FileRow[] };

const mb = (n: number) => (n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}MB` : `${Math.max(1, Math.round(n / 1000))}KB`);

function Row({ row, onChanged }: { row: FileRow; onChanged: (s: Status) => void }) {
  const [open, setOpen] = useState(!row.found);
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [askOverwrite, setAskOverwrite] = useState(false);

  const run = async (overwrite: boolean) => {
    if (!path.trim()) return;
    setBusy(true);
    setMessage(null);
    try {
      const res = await (await fetch(`${BASE_URL}/api/apple-files/import`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: row.key, source: path.trim(), overwrite }) })).json();
      if (res.error) {
        setMessage(res.error);
        setAskOverwrite(Boolean(res.exists));
      } else {
        setMessage(`가져왔어요: ${res.copied} (${mb(res.size)})`);
        setAskOverwrite(false);
        setPath("");
        onChanged({ folder: res.folder, files: res.files });
      }
    } catch (e) {
      setMessage((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div style={{ padding: "0.7rem 0", borderBottom: "1px solid rgba(128,128,128,0.2)" }}>
      <div style={{ display: "flex", gap: "0.6rem", alignItems: "baseline", flexWrap: "wrap" }}>
        <span aria-hidden>{row.found ? "✅" : "⬜"}</span>
        <b>{row.label}</b>
        <span style={{ color: "#999", fontSize: "0.8rem" }}>{row.found ? `${row.found}${row.size ? ` · ${mb(row.size)}` : ""}` : row.names.join(" / ")}</span>
        <button onClick={() => setOpen(!open)} style={{ marginLeft: "auto", background: "none", border: "none", color: "#6a9bd8", cursor: "pointer", font: "inherit", fontSize: "0.85rem" }}>
          {open ? "접기" : row.found ? "다른 파일로 바꾸기" : "어디서 받나요?"}
        </button>
      </div>
      <div style={{ color: "#999", fontSize: "0.85rem", marginTop: 2 }}>{row.purpose}</div>
      {open && (
        <div style={{ marginTop: "0.5rem", fontSize: "0.85rem" }}>
          <div style={{ color: "#999", lineHeight: 1.6 }}>
            받는 곳: {row.source}
            <br />
            두는 곳: 위에 저장한 Apple 폴더 안, 파일 이름은 <code>{row.names[0]}</code>
            {row.names.length > 1 ? ` (또는 ${row.names.slice(1).join(", ")})` : ""} 그대로.
          </div>
          <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.5rem", flexWrap: "wrap" }}>
            <input
              value={path}
              onChange={(e) => setPath(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && run(false)}
              placeholder="다른 곳에 받아 둔 파일 또는 폴더 경로 (예: /Users/me/Downloads/전체.xml)"
              style={{ flex: "1 1 280px", padding: "0.4rem 0.6rem", minWidth: 0 }}
            />
            <button onClick={() => run(false)} disabled={busy || !path.trim()} style={{ padding: "0.35rem 0.9rem" }}>
              {busy ? "가져오는 중..." : "이 폴더로 가져오기"}
            </button>
            {askOverwrite && (
              <button onClick={() => run(true)} disabled={busy} style={{ padding: "0.35rem 0.9rem", fontWeight: 700 }}>
                덮어쓰기
              </button>
            )}
          </div>
          {message && <div style={{ marginTop: 6, color: message.startsWith("가져왔어요") ? "#2a2" : "#d66" }}>{message}</div>}
        </div>
      )}
    </div>
  );
}

export function AppleFiles({ appleDir }: { appleDir: string }) {
  const [status, setStatus] = useState<Status | null>(null);
  const load = useCallback(() => {
    fetch(`${BASE_URL}/api/apple-files`)
      .then((r) => r.json())
      .then((d) => setStatus(d as Status))
      .catch(() => {});
  }, []);
  useEffect(load, [load, appleDir]);

  if (!appleDir) {
    return (
      <p style={{ color: "#999", fontSize: "0.85rem", margin: "0 0 0.9rem" }}>
        위에 Apple Music 폴더 경로를 저장하면, 어떤 파일이 있고 어떤 파일을 어디에 두면 되는지 안내가 나와요.
      </p>
    );
  }
  if (!status) return null;
  const found = status.files.filter((f) => f.found).length;
  return (
    <details style={{ margin: "0 0 1rem", border: "1px solid rgba(128,128,128,0.25)", borderRadius: 8, padding: "0.6rem 0.9rem" }} open={found < 3}>
      <summary style={{ cursor: "pointer", fontWeight: 600 }}>
        Apple 파일 안내 <span style={{ color: "#999", fontWeight: 400, fontSize: "0.85rem" }}>({found}/{status.files.length}개 있음)</span>
      </summary>
      <div style={{ color: "#999", fontSize: "0.8rem", margin: "0.5rem 0" }}>
        폴더: {status.folder} · 파일이 없어도 앱은 Last.fm 데이터만으로 동작하고, 해당 기능만 건너뛰어요.
      </div>
      {status.files.map((f) => (
        <Row key={`${f.key}|${f.found}`} row={f} onChanged={setStatus} />
      ))}
    </details>
  );
}
