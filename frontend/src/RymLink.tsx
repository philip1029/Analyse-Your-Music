import { rymUrl, type RymType } from "./rym";

// "RYM ↗": RateYourMusic 에서 이 이름을 검색하는 새 탭 링크
export function RymLink({ term, type, label = "RYM", title }: { term: string; type: RymType; label?: string; title?: string }) {
  const kind = { all: "전체", artist: "아티스트", release: "앨범", song: "곡" }[type];
  return (
    <a
      className="aym-rym"
      href={rymUrl(term, type)}
      target="_blank"
      rel="noopener noreferrer"
      title={title ?? `RateYourMusic에서 ‘${term}’ ${kind} 검색`}
      onClick={(e) => e.stopPropagation()}
    >
      {label} <span aria-hidden>↗</span>
    </a>
  );
}
