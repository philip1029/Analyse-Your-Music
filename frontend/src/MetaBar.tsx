import { useEffect, useState } from "react";
import { BASE_URL } from "./config";

// 스크로블이 반영된 뒤 백그라운드로 채우는 곡 길이·장르 태그·앨범 발매연도의 진행 표시.
// 새로고침은 스크로블 받기·정리만 기다리고, 이 부가 정보는 화면을 갱신한 뒤에 따로 채운다 (서버의 /api/refresh/meta-status).
// 채우는 동안에는 작은 진행 막대를 보여 주고, 끝나면 무엇을 얼마나 채웠는지 알려 준다.

type Result = {
  error?: string;
  durations?: { error?: string; found?: number; unknown?: number; remaining?: number } | null;
  tags?: { error?: string; fetched?: number; remaining?: number } | null;
  album_years?: { error?: string; started?: boolean } | null;
};
type Status = { running: boolean; done: boolean; percent: number; label: string; step: number; steps: number; result: Result | null; ended_at: number | null; ended_ago: number | null };

const SEEN_KEY = "aym-meta-seen";   // 이미 본 결과는 다시 알리지 않는다 (서버는 마지막 결과를 메모리에 계속 들고 있다)
const RECENT_SEC = 600;
const seen = (at: number | null) => {
  try {
    return at !== null && sessionStorage.getItem(SEEN_KEY) === String(at);
  } catch {
    return false;
  }
};
const markSeen = (at: number | null) => {
  try {
    if (at !== null) sessionStorage.setItem(SEEN_KEY, String(at));
  } catch {
    /* 저장할 수 없으면 그냥 넘어간다 */
  }
};

function summarize(r: Result): { parts: string[]; changed: boolean } {
  if (r.error) return { parts: [`부가 정보를 채우지 못했어요: ${r.error}`], changed: false };
  const parts: string[] = [];
  let changed = false;
  const d = r.durations;
  if (d?.error) parts.push(`곡 길이 조회 실패: ${d.error}`);
  else if (d && (d.found || d.unknown)) {
    parts.push(`곡 길이 ${d.found ?? 0}곡 추가${d.unknown ? ` (못 찾음 ${d.unknown})` : ""}${d.remaining ? ` · 남은 ${d.remaining}곡은 다음에` : ""}`);
    if (d.found) changed = true;
  }
  const t = r.tags;
  if (t?.error) parts.push(`태그 조회 실패: ${t.error}`);
  else if (t?.fetched) {
    parts.push(`아티스트 태그 ${t.fetched}명 추가${t.remaining ? ` · 남은 ${t.remaining}명은 다음에` : ""}`);
    changed = true;
  }
  if (r.album_years?.error) parts.push(`앨범 연도 조회를 시작하지 못했어요: ${r.album_years.error}`);
  else if (r.album_years?.started) parts.push("앨범 발매연도는 계속 백그라운드로 채워져요");
  return { parts, changed };
}

export function MetaBar() {
  const [status, setStatus] = useState<Status | null>(null);
  const [dismissed, setDismissed] = useState(false);

  // 처음 한 번 물어서, 돌고 있으면 끝날 때까지 짧게 묻는다
  useEffect(() => {
    let cancelled = false;
    let timer = 0;
    const poll = () =>
      fetch(`${BASE_URL}/api/refresh/meta-status`)
        .then((r) => r.json())
        .then((s: Status) => {
          if (cancelled) return;
          setStatus(s);
          if (s.running) timer = window.setTimeout(poll, 1200);
        })
        .catch(() => undefined);
    poll();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, []);

  if (!status || dismissed) return null;
  if (!status.running && !(status.done && status.result && (status.ended_ago ?? Infinity) < RECENT_SEC && !seen(status.ended_at))) return null;

  if (status.running) {
    const percent = Math.max(4, Math.min(100, status.percent));
    return (
      <div className="aym-panel" role="status" style={{ marginTop: "1rem", display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 260px", minWidth: 220 }}>
          <div style={{ fontSize: "0.85rem", color: "var(--text-2)", marginBottom: 6 }}>
            스크로블은 반영됐어요. 곡 정보를 채우는 중… <span style={{ color: "var(--text-3)" }}>({status.step}/{status.steps} {status.label})</span>
          </div>
          <div style={{ height: 6, borderRadius: 3, background: "var(--surface-2)", overflow: "hidden" }}>
            <div style={{ width: `${percent}%`, height: "100%", borderRadius: 3, background: "var(--album)", transition: "width 500ms cubic-bezier(0.22, 1, 0.36, 1)" }} />
          </div>
        </div>
      </div>
    );
  }

  const { parts, changed } = summarize(status.result!);
  if (!parts.length) return null;
  return (
    <div className="aym-panel" role="status" style={{ marginTop: "1rem", display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap", borderColor: "rgba(97,212,182,0.4)" }}>
      <div style={{ flex: "1 1 260px", fontSize: "0.9rem", color: "var(--text-2)" }}>✅ 곡 정보를 모두 채웠어요 · {parts.join(" · ")}</div>
      <div style={{ display: "flex", gap: "0.5rem" }}>
        {changed && (
          <button
            onClick={() => {
              markSeen(status.ended_at);
              window.location.reload();
            }}
          >
            화면에 반영
          </button>
        )}
        <button
          onClick={() => {
            markSeen(status.ended_at);
            setDismissed(true);
          }}
        >
          닫기
        </button>
      </div>
    </div>
  );
}
