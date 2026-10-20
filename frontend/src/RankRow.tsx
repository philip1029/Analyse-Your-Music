import type { ReactNode } from "react";
import { Cover } from "./Cover";

// Last.fm 라이브러리 스타일의 순위 한 줄: 순위 · 커버 · 이름/부제 · 막대(수치)
export type RankKind = "artist" | "album" | "track";
export type RankItem = { name: string; artist: string | null; album?: string | null; count: number };

export const LINE = "1px solid rgba(128,128,128,0.25)";
export const BAR = "rgba(136,132,216,0.32)";

export function RankRow({
  rank,
  item,
  max,
  kind,
  onOpen,
  showArtist = true,
  extra,
  barFraction,
  barText,
}: {
  rank: number;
  item: RankItem;
  max: number;
  kind: RankKind;
  onOpen?: () => void;
  showArtist?: boolean;
  extra?: ReactNode;          // 이름 아래에 붙일 내용 (예: 월별 미니 그래프)
  barFraction?: number;       // 막대 길이(0~1). 기본은 count / max
  barText?: string;           // 막대 안 글자. 기본은 count
}) {
  const subtitle = showArtist ? item.artist : null;
  const fraction = barFraction ?? item.count / max;
  const text = barText ?? `${item.count.toLocaleString()}${rank === 1 ? " scrobbles" : ""}`;
  return (
    <div
      role={onOpen ? "button" : undefined}
      tabIndex={onOpen ? 0 : undefined}
      onClick={onOpen}
      onKeyDown={onOpen ? (e) => e.key === "Enter" && onOpen() : undefined}
      style={{ display: "flex", alignItems: "center", gap: "0.9rem", padding: "0.55rem 0.25rem", borderBottom: LINE, cursor: onOpen ? "pointer" : "default", textAlign: "left" }}
    >
      <span style={{ width: 28, textAlign: "right", color: "#999", flexShrink: 0 }}>{rank}</span>
      {kind === "artist" ? (
        <Cover kind="artist" artist={item.name} size={44} />
      ) : (
        <Cover kind="album" artist={item.artist} album={kind === "album" ? item.name : item.album} size={44} />
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 700, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.name}</div>
        {subtitle && <div style={{ color: "#999", fontSize: "0.9rem", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{subtitle}</div>}
        {extra}
      </div>
      <div style={{ width: "38%", maxWidth: 360, flexShrink: 0 }}>
        <div style={{ width: `${Math.max(4, Math.min(1, fraction) * 100)}%`, background: BAR, padding: "0.5rem 0.6rem", borderRadius: 2, whiteSpace: "nowrap", boxSizing: "border-box" }}>
          {text}
        </div>
      </div>
    </div>
  );
}
