// RateYourMusic 검색 링크. 앱이 모르는 정보(앨범 발매연도 등)를 직접 찾아볼 때 쓴다.
// 검색 종류: 전체(빈 값) · 아티스트(a) · 릴리스=앨범(l) · 곡(z)
export type RymType = "all" | "artist" | "release" | "song";

const SEARCH_TYPE: Record<RymType, string> = { all: "", artist: "a", release: "l", song: "z" };

export function rymUrl(term: string, type: RymType = "all"): string {
  return `https://rateyourmusic.com/search?searchterm=${encodeURIComponent(term.trim())}&searchtype=${SEARCH_TYPE[type]}`;
}
