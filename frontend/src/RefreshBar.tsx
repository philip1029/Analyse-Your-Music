import { useEffect, useState } from "react";
import { BASE_URL } from "./config";

// "🔄 최신 스크롭 불러오기" 진행률 막대. 새로고침이 도는 동안 서버의 /api/refresh/status 를 짧게 물어
// 현재 단계 이름과 백분율을 보여 준다 (Last.fm 받기는 페이지 수까지).

type Status = { running: boolean; done: boolean; percent: number; label: string; detail: string; step: number; steps: number; elapsed: number };

export function RefreshBar({ active }: { active: boolean }) {
  const [status, setStatus] = useState<Status | null>(null);

  useEffect(() => {
    if (!active) {
      setStatus(null);
      return;
    }
    let cancelled = false;
    const poll = () =>
      fetch(`${BASE_URL}/api/refresh/status`)
        .then((r) => r.json())
        .then((s: Status) => !cancelled && setStatus(s))
        .catch(() => {});                                   // 잠깐 응답이 없어도 다음 번에 다시 묻는다
    poll();
    const id = window.setInterval(poll, 600);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [active]);

  if (!active) return null;
  const percent = Math.max(2, Math.min(100, status?.percent ?? 0));
  return (
    <div role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(percent)} aria-label="최신 스크롭 불러오는 중" style={{ flex: "1 1 260px", minWidth: 220, maxWidth: 460 }}>
      <div style={{ height: 8, borderRadius: 4, background: "rgba(128,128,128,0.25)", overflow: "hidden" }}>
        <div style={{ width: `${percent}%`, height: "100%", borderRadius: 4, background: "#8884d8", transition: "width 500ms cubic-bezier(0.22, 1, 0.36, 1)" }} />
      </div>
      <div style={{ display: "flex", justifyContent: "space-between", gap: "0.8rem", marginTop: 4, fontSize: "0.8rem", color: "#999" }}>
        <span>
          {status ? `${status.step}/${status.steps} ${status.label}${status.detail ? ` (${status.detail})` : ""}` : "준비 중"}
        </span>
        <span>{Math.round(percent)}%</span>
      </div>
    </div>
  );
}
