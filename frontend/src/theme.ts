// 앱 전체에서 쓰는 카테고리 색 (Last.fm 리포트 방식): 아티스트=보라, 앨범=민트, 트랙=파랑.
// 통계 카드, 순위 막대, 버튼, 구역 제목이 모두 같은 색을 쓴다.

export type Cat = "artist" | "album" | "track";

export const CAT: Record<Cat, { main: string; soft: string; label: string }> = {
  artist: { main: "#c490ff", soft: "rgba(196,144,255,0.34)", label: "아티스트" },
  album: { main: "#61d4b6", soft: "rgba(97,212,182,0.34)", label: "앨범" },
  track: { main: "#469df8", soft: "rgba(70,157,248,0.34)", label: "트랙" },
};

export const SCROBBLE_COLOR = "#ffcace";      // 스크로블(전체 재생 수) 카드: 연한 분홍
export const MUTED = "#a7acb7";               // 보조 글자색

// 카테고리 선택 알약: 켜지면 카테고리 색으로 채우고, 꺼져 있어도 아래 색 줄로 어떤 색인지 보인다
export function catPill(active: boolean, color: string): import("react").CSSProperties {
  return {
    padding: "0.38rem 1rem",
    border: "none",
    borderRadius: 999,
    background: active ? color : "var(--surface-2)",
    color: active ? "#1a1b1e" : "var(--text)",
    fontWeight: active ? 800 : 600,
    boxShadow: active ? "none" : `inset 0 -3px 0 ${color}`,
  };
}
