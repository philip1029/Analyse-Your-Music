import { useEffect, useRef, useState, type CSSProperties } from "react";
import { BASE_URL } from "./config";

// 같은 커버를 여러 번 요청하지 않도록 세션 동안 결과를 기억한다 (null = 커버 없음)
const coverMemo = new Map<string, Promise<string | null>>();

// 동시에 보내는 커버 요청 수를 제한한다. 브라우저는 서버당 연결이 6개뿐이라, 커버 요청이 몰리면
// 목록·상세 같은 다른 API 응답이 그 뒤에 줄을 서게 된다.
const MAX_CONCURRENT = 3;
let active = 0;
const waiting: (() => void)[] = [];

function limited<T>(task: () => Promise<T>): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const run = () => {
      active++;
      task()
        .then(resolve, reject)
        .finally(() => {
          active--;
          waiting.shift()?.();
        });
    };
    if (active < MAX_CONCURRENT) run();
    else waiting.push(run);
  });
}

function fetchCover(path: string): Promise<string | null> {
  let pending = coverMemo.get(path);
  if (!pending) {
    pending = limited(() => fetch(`${BASE_URL}${path}`))
      .then((res) => res.json())
      .then((data) => (data.url as string | null) ?? null)
      .catch(() => {
        coverMemo.delete(path); // 일시적 실패는 다음에 다시 시도
        return null;
      });
    coverMemo.set(path, pending);
  }
  return pending;
}

// 앨범 커버(Last.fm) 또는 아티스트 사진(Deezer). 없으면 회색 칸에 첫 글자를 보여 준다.
export function Cover({
  kind,
  artist,
  album,
  size = 48,
}: {
  kind: "album" | "artist";
  artist: string | null;
  album?: string | null;
  size?: number;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [visible, setVisible] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // 화면 근처에 왔을 때만 커버를 요청한다 (긴 목록에서 보이지 않는 항목까지 요청하지 않도록)
  useEffect(() => {
    const el = ref.current;
    if (!el || typeof IntersectionObserver === "undefined") {
      setVisible(true);
      return;
    }
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setVisible(true);
          io.disconnect();
        }
      },
      { rootMargin: "200px" }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    setUrl(null);
    setFailed(false);
    let path: string | null = null;
    if (kind === "artist" && artist) path = `/api/artist-art?artist=${encodeURIComponent(artist)}`;
    if (kind === "album" && artist && album) path = `/api/album-art?artist=${encodeURIComponent(artist)}&album=${encodeURIComponent(album)}`;
    if (path && visible) {
      fetchCover(path).then((u) => {
        if (!cancelled) setUrl(u);
      });
    }
    return () => {
      cancelled = true;
    };
  }, [kind, artist, album, visible]);

  const label = kind === "artist" ? artist : album;
  const box: CSSProperties = {
    width: size,
    height: size,
    flexShrink: 0,
    borderRadius: kind === "artist" ? "50%" : 4,
    background: "#e6e6e6",
    color: "#999",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: size * 0.4,
    overflow: "hidden",
  };

  return (
    <div ref={ref} style={box}>
      {url && !failed ? (
        <img src={url} alt={label ?? ""} width={size} height={size} loading="lazy" onError={() => setFailed(true)} style={{ objectFit: "cover", display: "block" }} />
      ) : label ? (
        Array.from(label)[0]
      ) : (
        "♪"
      )}
    </div>
  );
}
