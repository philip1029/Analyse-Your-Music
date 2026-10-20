// 앱 전체에서 쓰는 카테고리 색 (Last.fm 리포트 방식): 아티스트=보라, 앨범=민트, 트랙=파랑.
// 통계 카드, 순위 막대, 버튼, 구역 제목이 모두 같은 색을 쓴다.

export type Cat = "artist" | "album" | "track";

export const CAT: Record<Cat, { main: string; soft: string; label: string }> = {
  artist: { main: "#c490ff", soft: "rgba(196,144,255,0.34)", label: "아티스트" },
  album: { main: "#61d4b6", soft: "rgba(97,212,182,0.34)", label: "앨범" },
  track: { main: "#469df8", soft: "rgba(70,157,248,0.34)", label: "트랙" },
};

export const SCROBBLE_COLOR = "#ffcace";      // 스크로블(전체 재생 수) 카드: 연한 분홍
export const CARD_INK = "#1a1b1e";            // 색 카드 위의 글자색
export const MUTED = "#a7acb7";               // 보조 글자색

// 오른쪽 위 모서리를 접은 모양 (dog-ear)
export const DOG_EAR = "polygon(0 0, calc(100% - 20px) 0, 100% 20px, 100% 100%, 0 100%)";
