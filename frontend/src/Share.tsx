import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { BASE_URL } from "./config";
import { agoText, fmtHM, withWeekday } from "./format";
import { fmtDuration } from "./RankRow";

// 공유용 이미지 카드: 기간별 요약 / Top 순위 / 청취 시계, 그리고 앨범·아티스트·곡 한 개의 카드를 canvas 로 그려 PNG 로 저장한다.
// 화면 곳곳의 공유 버튼(ShareButton)이 이 대화상자를 연다 (ShareProvider 가 App 전체를 감싼다).
// 커버 이미지는 CORS 때문에 백엔드 이미지 프록시(/api/image-proxy)로 받아야 canvas 를 저장할 수 있다.

const W = 1080;
const H = 1920;
const PAD = 96;
const FONT = '"Apple SD Gothic Neo","Pretendard","Noto Sans KR",system-ui,sans-serif';

type Theme = { id: string; bg: string; fg: string; sub: string; border: string | null; accent: string };

const DARK = { bg: "#121214", fg: "#ffffff", sub: "#9a9aa2" };
const THEMES: Theme[] = [
  { id: "dark", ...DARK, border: "#ffffff", accent: "#ffffff" },
  { id: "purple", ...DARK, border: "#b794f6", accent: "#b794f6" },
  { id: "green", ...DARK, border: "#4fd1a5", accent: "#4fd1a5" },
  { id: "blue", ...DARK, border: "#4c8dff", accent: "#4c8dff" },
  { id: "red", ...DARK, border: "#ff5a5f", accent: "#ff5a5f" },
  { id: "white", bg: "#ffffff", fg: "#111111", sub: "#6b6b73", border: null, accent: "#111111" },
  { id: "lilac", bg: "#ecd4ff", fg: "#2a1740", sub: "#6b4f87", border: null, accent: "#7c3aed" },
  { id: "mint", bg: "#c5f0dc", fg: "#0f3b2b", sub: "#3f7a63", border: null, accent: "#10b981" },
  { id: "sky", bg: "#bcd7ff", fg: "#0e2a55", sub: "#456a9c", border: null, accent: "#2563eb" },
  { id: "rose", bg: "#ffd9d9", fg: "#4a1414", sub: "#8f5a5a", border: null, accent: "#ef4444" },
];

type Period = "all" | "year" | "month" | "week";
type CardType = "summary" | "top" | "clock";
type Cat = "artist" | "album" | "track";
type Metric = "plays" | "time";

type TopItem = { name: string; artist: string | null; album?: string | null; count: number; seconds?: number };
type Report = {
  username: string | null;
  label: string;
  range_text: string;
  scrobbles: number;
  seconds: number;
  artists: number;
  albums: number;
  tracks: number;
  tags: string[];
  tops: Record<Cat, { plays: TopItem[]; time: TopItem[] }>;
  busiest_day: { date: string; seconds: number; plays: number };
  hourly_plays: number[];
  hourly_minutes: number[];
};
type PeriodOption = { key: string; label: string; scrobbles: number; partial: boolean };

// ---------------------------------------------------------------- 이미지 로딩 (프록시 경유)

const imageMemo = new Map<string, Promise<HTMLImageElement | null>>();

function loadImage(url: string | null): Promise<HTMLImageElement | null> {
  if (!url) return Promise.resolve(null);
  let p = imageMemo.get(url);
  if (!p) {
    p = new Promise((resolve) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null);
      img.src = `${BASE_URL}/api/image-proxy?url=${encodeURIComponent(url)}`;
    });
    imageMemo.set(url, p);
  }
  return p;
}

async function coverUrl(kind: "album" | "artist", artist: string | null, album?: string | null): Promise<string | null> {
  try {
    const path =
      kind === "artist"
        ? `/api/artist-art?artist=${encodeURIComponent(artist ?? "")}`
        : `/api/album-art?artist=${encodeURIComponent(artist ?? "")}&album=${encodeURIComponent(album ?? "")}`;
    if (!artist || (kind === "album" && !album)) return null;
    const d = await (await fetch(`${BASE_URL}${path}`)).json();
    return (d.url as string | null) ?? null;
  } catch {
    return null;
  }
}

const cover = (kind: "album" | "artist", artist: string | null, album?: string | null) =>
  coverUrl(kind, artist, album).then(loadImage);

// ---------------------------------------------------------------- canvas 그리기 도구

type Ctx = CanvasRenderingContext2D;

function setFont(ctx: Ctx, size: number, weight: number | string = 400) {
  ctx.font = `${weight} ${size}px ${FONT}`;
}

// 글자가 maxW 를 넘으면 글자 크기를 줄여서 한 줄에 맞춘다
function fitFont(ctx: Ctx, text: string, maxW: number, size: number, weight: number | string, min = 22): number {
  let s = size;
  setFont(ctx, s, weight);
  while (ctx.measureText(text).width > maxW && s > min) {
    s -= 2;
    setFont(ctx, s, weight);
  }
  return s;
}

// 줄바꿈해서 그린다 (maxLines 를 넘으면 …). 공백이 있으면 단어 단위로, 한 단어가 너무 길거나 공백이 없는 글(한글·일본어)은 글자 단위로 나눈다.
// 마지막 줄의 y 다음 위치를 돌려준다.
function drawWrapped(ctx: Ctx, text: string, x: number, y: number, maxW: number, lineH: number, maxLines: number): number {
  const lines: string[] = [];
  let line = "";
  const push = (piece: string) => {
    if (ctx.measureText(line + piece).width <= maxW) {
      line += piece;
    } else if (line.trim()) {
      lines.push(line.trimEnd());
      line = piece.trimStart();
    } else {
      line = piece;
    }
  };
  for (const token of text.split(/(?<= )/)) {
    if (ctx.measureText(token).width <= maxW) push(token);
    else for (const ch of Array.from(token)) push(ch);          // 한 단어가 한 줄보다 길면 글자 단위
  }
  if (line.trim()) lines.push(line.trimEnd());
  const shown = lines.slice(0, maxLines);
  if (lines.length > maxLines) {
    let last = shown[maxLines - 1];
    while (last && ctx.measureText(last + "…").width > maxW) last = last.slice(0, -1);
    shown[maxLines - 1] = last + "…";
  }
  shown.forEach((l, i) => ctx.fillText(l, x, y + i * lineH));
  return y + shown.length * lineH;
}

function clip(ctx: Ctx, text: string, maxW: number): string {
  if (ctx.measureText(text).width <= maxW) return text;
  let t = text;
  while (t && ctx.measureText(t + "…").width > maxW) t = t.slice(0, -1);
  return t + "…";
}

function roundRectPath(ctx: Ctx, x: number, y: number, w: number, h: number, r: number) {
  ctx.beginPath();
  ctx.moveTo(x + r, y);
  ctx.arcTo(x + w, y, x + w, y + h, r);
  ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r);
  ctx.arcTo(x, y, x + w, y, r);
  ctx.closePath();
}

// 이미지를 정사각(또는 원) 칸에 꽉 채워(cover) 그린다. 이미지가 없으면 회색 칸에 첫 글자.
function drawCover(ctx: Ctx, img: HTMLImageElement | null, x: number, y: number, w: number, h: number, t: Theme, round = false, letter = "") {
  ctx.save();
  if (round) {
    ctx.beginPath();
    ctx.arc(x + w / 2, y + h / 2, w / 2, 0, Math.PI * 2);
  } else roundRectPath(ctx, x, y, w, h, 10);
  ctx.clip();
  if (img) {
    const s = Math.max(w / img.width, h / img.height);
    const dw = img.width * s;
    const dh = img.height * s;
    ctx.drawImage(img, x + (w - dw) / 2, y + (h - dh) / 2, dw, dh);
  } else {
    ctx.fillStyle = t.border ? "#2a2a30" : "rgba(0,0,0,0.12)";
    ctx.fillRect(x, y, w, h);
    ctx.fillStyle = t.sub;
    setFont(ctx, h * 0.4, 700);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(Array.from(letter)[0] ?? "♪", x + w / 2, y + h / 2);
  }
  ctx.restore();
}

function frame(ctx: Ctx, t: Theme) {
  ctx.fillStyle = t.bg;
  ctx.fillRect(0, 0, W, H);
  if (t.border) {
    ctx.strokeStyle = t.border;
    ctx.lineWidth = 3;
    ctx.strokeRect(36, 36, W - 72, H - 72);
  }
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";
}

function footer(ctx: Ctx, t: Theme) {
  ctx.fillStyle = t.sub;
  setFont(ctx, 34, 700);
  ctx.textAlign = "right";
  ctx.fillText("Analyse Your Music", W - PAD, H - PAD + 10);
  ctx.textAlign = "left";
}

const headerLine = (r: Report) => `${r.username ? r.username + ", " : ""}${r.range_text}`;

// ---------------------------------------------------------------- 카드: 요약

// 이미지는 먼저 전부 받고(loadXxx), 그린 뒤에는 await 없이 한 번에 그린다 (그리는 도중에 다른 요청이 끼어들어 겹쳐 그려지지 않게)
type Img = HTMLImageElement | null;

const loadSummaryAssets = (r: Report): Promise<Img[]> =>
  Promise.all(r.tops.album.plays.slice(0, 5).map((a) => cover("album", a.artist, a.name)));

function drawSummary(ctx: Ctx, r: Report, t: Theme, images: Img[]) {
  frame(ctx, t);
  const albums = r.tops.album.plays;
  const [big, ...small] = images;

  ctx.fillStyle = t.fg;
  setFont(ctx, 36, 500);
  ctx.fillText(headerLine(r), PAD, PAD + 40);

  setFont(ctx, 150, 800);
  ctx.fillText(r.scrobbles.toLocaleString(), PAD, 420);
  const numW = ctx.measureText(r.scrobbles.toLocaleString()).width;
  setFont(ctx, 56, 500);
  ctx.fillStyle = t.sub;
  ctx.fillText("스크로블", PAD + numW + 24, 420);
  ctx.fillStyle = t.fg;
  setFont(ctx, 44, 600);
  ctx.fillText(`청취 시간 ${fmtHM(r.seconds)}`, PAD, 500);

  // 아티스트·앨범·트랙 수
  const cols: [string, number][] = [["아티스트", r.artists], ["앨범", r.albums], ["트랙", r.tracks]];
  cols.forEach(([name, n], i) => {
    const x = PAD + i * 300;
    setFont(ctx, 66, 800);
    ctx.fillStyle = t.fg;
    ctx.fillText(n.toLocaleString(), x, 650);
    setFont(ctx, 32, 500);
    ctx.fillStyle = t.sub;
    ctx.fillText(name, x, 696);
  });

  // 앨범 커버 콜라주: 큰 칸 하나 + 작은 칸 4개
  const cy = 760;
  drawCover(ctx, big ?? null, PAD, cy, 432, 432, t, false, albums[0]?.name);
  small.forEach((img, i) => {
    const x = PAD + 432 + 24 + (i % 2) * (204 + 24);
    const y = cy + Math.floor(i / 2) * (204 + 24);
    drawCover(ctx, img, x, y, 204, 204, t, false, albums[i + 1]?.name);
  });

  // Top 항목
  const top = r.tops;
  const rows: [string, string, string | null][] = [
    ["Top 아티스트", top.artist.plays[0]?.name ?? "-", null],
    ["Top 앨범", top.album.plays[0]?.name ?? "-", top.album.plays[0]?.artist ?? null],
    ["Top 트랙", top.track.plays[0]?.name ?? "-", top.track.plays[0]?.artist ?? null],
    ["Top 태그", r.tags.length ? r.tags.join(", ") : "-", null],
  ];
  let y = 1300;
  const xv = PAD + 280;
  rows.forEach(([label, value, sub]) => {
    ctx.fillStyle = t.sub;
    setFont(ctx, 30, 500);
    ctx.fillText(label, PAD, y);
    ctx.fillStyle = t.fg;
    fitFont(ctx, value, W - PAD - xv, 42, 700, 30);   // 긴 값은 글자 크기를 줄여 두 줄 안에 담는다
    let ny = drawWrapped(ctx, value, xv, y, W - PAD - xv, 52, 2);
    if (sub) {
      ctx.fillStyle = t.sub;
      setFont(ctx, 32, 400);
      ctx.fillText(clip(ctx, sub, W - PAD - xv), xv, ny - 4);
      ny += 40;
    }
    y = Math.max(ny, y + 52) + 44;
  });
  footer(ctx, t);
}

// ---------------------------------------------------------------- 카드: Top 순위

const loadTopAssets = (r: Report, cat: Cat, metric: Metric): Promise<Img[]> =>
  Promise.all(
    r.tops[cat][metric === "time" ? "time" : "plays"].map((it) =>
      cat === "artist" ? cover("artist", it.name) : cover("album", it.artist, cat === "album" ? it.name : it.album)
    )
  );

function drawTop(ctx: Ctx, r: Report, t: Theme, cat: Cat, metric: Metric, imgs: Img[]) {
  frame(ctx, t);
  const items = r.tops[cat][metric === "time" ? "time" : "plays"];

  ctx.fillStyle = t.sub;
  setFont(ctx, 36, 500);
  ctx.fillText(headerLine(r), PAD, PAD + 40);
  ctx.fillStyle = t.fg;
  setFont(ctx, 110, 800);
  ctx.fillText(`Top ${cat === "artist" ? "아티스트" : cat === "album" ? "앨범" : "트랙"}`, PAD, 330);
  setFont(ctx, 40, 500);
  ctx.fillStyle = t.sub;
  ctx.fillText(metric === "time" ? "청취 시간 순 (스크로블 × 곡 길이)" : "재생 횟수 순", PAD, 400);

  const value = (it: TopItem) => (metric === "time" ? it.seconds ?? 0 : it.count);
  const max = Math.max(1, ...items.map(value));
  const rowH = 230;
  items.forEach((it, i) => {
    const y = 500 + i * rowH;
    ctx.fillStyle = t.sub;
    setFont(ctx, 50, 600);
    ctx.textAlign = "right";
    ctx.fillText(String(i + 1), PAD + 50, y + 100);
    ctx.textAlign = "left";
    drawCover(ctx, imgs[i], PAD + 90, y, 160, 160, t, cat === "artist", it.name);

    const x = PAD + 290;
    const w = W - PAD - x;
    ctx.fillStyle = t.fg;
    fitFont(ctx, it.name, w, 46, 700, 28);
    ctx.fillText(clip(ctx, it.name, w), x, y + 52);
    if (cat !== "artist" && it.artist) {
      ctx.fillStyle = t.sub;
      setFont(ctx, 32, 400);
      ctx.fillText(clip(ctx, it.artist, w), x, y + 96);
    }
    // 막대 + 수치
    const barY = y + 118;
    const bw = Math.max(16, (w * value(it)) / max);
    ctx.fillStyle = t.accent;
    ctx.globalAlpha = 0.85;
    roundRectPath(ctx, x, barY, bw, 34, 6);
    ctx.fill();
    ctx.globalAlpha = 1;
    setFont(ctx, 30, 600);
    const label = metric === "time" ? fmtHM(it.seconds ?? 0) : `${it.count.toLocaleString()}회`;
    const lw = ctx.measureText(label).width;
    const inside = bw + 24 + lw > w;                     // 막대가 길어 글자가 밖에 들어갈 자리가 없으면 막대 안쪽에 쓴다
    ctx.fillStyle = inside ? t.bg : t.fg;
    ctx.fillText(label, inside ? x + bw - lw - 12 : x + bw + 16, barY + 27);
  });
  footer(ctx, t);
}

// ---------------------------------------------------------------- 카드: 청취 시계

function hourKo(h: number) {
  const hh = h % 12 === 0 ? 12 : h % 12;
  return `${h < 12 ? "오전" : "오후"} ${hh}시`;
}

function drawClock(ctx: Ctx, r: Report, t: Theme, metric: Metric) {
  frame(ctx, t);
  const data = metric === "time" ? r.hourly_minutes : r.hourly_plays;
  const max = Math.max(1, ...data);
  const busiest = data.indexOf(Math.max(...data));
  const fmt = (v: number) => (metric === "time" ? fmtHM(v * 60) : `${v.toLocaleString()}회`);

  ctx.fillStyle = t.sub;
  setFont(ctx, 36, 500);
  ctx.fillText(headerLine(r), PAD, PAD + 40);
  ctx.fillStyle = t.fg;
  setFont(ctx, 110, 800);
  ctx.fillText("청취 시계", PAD, 330);
  setFont(ctx, 40, 500);
  ctx.fillStyle = t.sub;
  ctx.fillText(metric === "time" ? "시간대별 청취 시간" : "시간대별 재생 횟수", PAD, 400);

  const cx = W / 2;
  const cy = 940;
  const rIn = 130;
  const rMax = 400;
  const gap = (2 * Math.PI) / 180;
  const base = t.border ? "rgba(255,255,255,0.10)" : "rgba(0,0,0,0.10)";
  data.forEach((v, h) => {
    const a0 = (h * 15 * Math.PI) / 180 - Math.PI / 2 + gap / 2;
    const a1 = ((h + 1) * 15 * Math.PI) / 180 - Math.PI / 2 - gap / 2;
    const wedge = (ro: number) => {
      ctx.beginPath();
      ctx.arc(cx, cy, ro, a0, a1);
      ctx.arc(cx, cy, rIn, a1, a0, true);
      ctx.closePath();
    };
    ctx.fillStyle = base;
    wedge(rMax);
    ctx.fill();
    if (v > 0) {
      ctx.fillStyle = t.accent;
      ctx.globalAlpha = 0.35 + 0.65 * (v / max);
      wedge(rIn + (rMax - rIn) * (v / max));
      ctx.fill();
      ctx.globalAlpha = 1;
    }
  });
  ctx.fillStyle = t.sub;
  setFont(ctx, 34, 600);
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ([[0, -64], [6, 0], [12, 64], [18, 0]] as [number, number][]).forEach(([hh, dy], i) => {
    const dx = i === 1 ? 64 : i === 3 ? -64 : 0;
    ctx.fillText(String(hh).padStart(2, "0"), cx + dx, cy + dy);
  });
  ctx.textAlign = "left";
  ctx.textBaseline = "alphabetic";

  ctx.fillStyle = t.sub;
  setFont(ctx, 32, 500);
  ctx.fillText("가장 붐비는 시간대", PAD, 1500);
  ctx.fillStyle = t.fg;
  setFont(ctx, 76, 800);
  ctx.fillText(hourKo(busiest), PAD, 1584);
  setFont(ctx, 38, 500);
  ctx.fillStyle = t.sub;
  ctx.fillText(fmt(data[busiest]), PAD, 1640);

  ctx.fillStyle = t.sub;
  setFont(ctx, 32, 500);
  ctx.fillText("가장 많이 들은 날", PAD + 520, 1500);
  ctx.fillStyle = t.fg;
  setFont(ctx, 44, 700);
  ctx.fillText(withWeekday(r.busiest_day.date), PAD + 520, 1584);
  setFont(ctx, 38, 500);
  ctx.fillStyle = t.sub;
  ctx.fillText(`${fmtHM(r.busiest_day.seconds)} · ${r.busiest_day.plays}회`, PAD + 520, 1640);
  footer(ctx, t);
}

// ---------------------------------------------------------------- 카드: 앨범 / 아티스트 / 곡 (대상 하나)

type SubjectCard = {
  kindLabel: string;                                   // "앨범" / "아티스트" / "곡"
  title: string;
  subtitle: string;
  round: boolean;                                      // 아티스트 사진은 원형
  coverKind: "album" | "artist";
  coverArtist: string | null;
  coverAlbum: string | null;
  stats: { label: string; value: string; sub?: string }[];
  listTitle: string | null;
  list: { name: string; count: number }[];
  monthly: { months: string[]; counts: number[] } | null;
  fileKey: string;
};

type Monthly = { months: string[]; counts: number[] };
type RawItem = { name: string; artist?: string | null; count: number };

const slug = (s: string) => s.replace(/[^\p{L}\p{N}]+/gu, "-").replace(/^-|-$/g, "").slice(0, 40);

function when(label: string, date: string) {
  return { label, value: date, sub: agoText(date) };
}

function normalizeAlbum(d: { name: string; artist: string | null; scrobbles: number; seconds: number; tracks_count: number; first_played: string; last_played: string; tracks: RawItem[]; monthly: Monthly }): SubjectCard {
  return {
    kindLabel: "앨범",
    title: d.name,
    subtitle: d.artist ?? "",
    round: false,
    coverKind: "album",
    coverArtist: d.artist,
    coverAlbum: d.name,
    stats: [
      { label: "스크로블", value: d.scrobbles.toLocaleString() },
      { label: "청취 시간", value: fmtHM(d.seconds) },
      { label: "트랙", value: `${d.tracks_count}곡` },
      when("처음 들은 날", d.first_played),
      when("마지막으로 들은 날", d.last_played),
    ],
    listTitle: "Top 트랙",
    list: d.tracks.slice(0, 5).map((t) => ({ name: t.name, count: t.count })),
    monthly: d.monthly,
    fileKey: `album-${slug(d.name)}`,
  };
}

function normalizeArtist(d: { name: string; scrobbles: number; seconds: number; albums_count: number; tracks_count: number; first_played: string; last_played: string; albums: RawItem[]; monthly: Monthly }): SubjectCard {
  return {
    kindLabel: "아티스트",
    title: d.name,
    subtitle: "",
    round: true,
    coverKind: "artist",
    coverArtist: d.name,
    coverAlbum: null,
    stats: [
      { label: "스크로블", value: d.scrobbles.toLocaleString() },
      { label: "청취 시간", value: fmtHM(d.seconds) },
      { label: "앨범 · 트랙", value: `${d.albums_count} · ${d.tracks_count}` },
      when("처음 들은 날", d.first_played),
      when("마지막으로 들은 날", d.last_played),
    ],
    listTitle: "Top 앨범",
    list: d.albums.slice(0, 5).map((a) => ({ name: a.name, count: a.count })),
    monthly: d.monthly,
    fileKey: `artist-${slug(d.name)}`,
  };
}

function normalizeTrack(d: { name: string; artist: string | null; album: string | null; scrobbles: number; seconds: number; duration?: number | null; first_played: string; last_played: string; albums: { name: string; count: number }[]; monthly: Monthly }): SubjectCard {
  return {
    kindLabel: "곡",
    title: d.name,
    subtitle: [d.artist, d.album].filter(Boolean).join(" · "),
    round: false,
    coverKind: "album",
    coverArtist: d.artist,
    coverAlbum: d.album,
    stats: [
      { label: "스크로블", value: d.scrobbles.toLocaleString() },
      { label: "청취 시간", value: fmtHM(d.seconds) },
      { label: "곡 길이", value: d.duration ? fmtDuration(d.duration) : "-" },
      when("처음 들은 날", d.first_played),
      when("마지막으로 들은 날", d.last_played),
    ],
    listTitle: d.albums.length > 1 ? "수록 앨범" : null,
    list: d.albums.slice(0, 5).map((a) => ({ name: a.name, count: a.count })),
    monthly: d.monthly,
    fileKey: `track-${slug(d.name)}`,
  };
}

const loadSubjectAssets = (c: SubjectCard): Promise<Img> => cover(c.coverKind, c.coverArtist, c.coverAlbum);

function drawSubject(ctx: Ctx, c: SubjectCard, t: Theme, username: string | null, image: Img) {
  frame(ctx, t);
  ctx.fillStyle = t.sub;
  setFont(ctx, 36, 500);
  ctx.fillText(`${username ? username + " · " : ""}${c.kindLabel}`, PAD, PAD + 40);

  // 커버(또는 아티스트 사진) + 오른쪽 통계 다섯 칸
  const cs = 540;
  const cy = 190;
  drawCover(ctx, image, PAD, cy, cs, cs, t, c.round, c.title);
  const sx = PAD + cs + 48;
  const sw = W - PAD - sx;
  let sy = cy + 40;                                    // 부가 줄(상대 날짜)이 있는 칸은 더 높게 잡는다
  c.stats.forEach((st) => {
    const y = sy;
    sy += st.sub ? 134 : 92;
    ctx.fillStyle = t.sub;
    setFont(ctx, 28, 500);
    ctx.fillText(st.label, sx, y);
    ctx.fillStyle = t.fg;
    fitFont(ctx, st.value, sw, 50, 800, 28);
    ctx.fillText(st.value, sx, y + 46);
    if (st.sub) {
      ctx.fillStyle = t.sub;
      setFont(ctx, 28, 400);
      ctx.fillText(st.sub, sx, y + 84);
    }
  });

  // 제목 / 부제
  ctx.fillStyle = t.fg;
  setFont(ctx, 84, 800);
  let y = drawWrapped(ctx, c.title, PAD, cy + cs + 120, W - 2 * PAD, 100, 2);
  if (c.subtitle) {
    ctx.fillStyle = t.sub;
    setFont(ctx, 42, 500);
    ctx.fillText(clip(ctx, c.subtitle, W - 2 * PAD), PAD, y - 20);
    y += 36;
  }

  // 목록 (Top 트랙 / Top 앨범 / 수록 앨범)
  let listBottom = y + 30;
  if (c.listTitle && c.list.length) {
    let ly = Math.max(y + 60, 1090);
    ctx.fillStyle = t.sub;
    setFont(ctx, 30, 600);
    ctx.fillText(c.listTitle, PAD, ly);
    ly += 24;
    const max = Math.max(1, ...c.list.map((x) => x.count));
    c.list.forEach((it, i) => {
      const ry = ly + i * 84;
      ctx.fillStyle = t.sub;
      setFont(ctx, 34, 600);
      ctx.textAlign = "right";
      ctx.fillText(String(i + 1), PAD + 36, ry + 56);
      ctx.textAlign = "left";
      ctx.fillStyle = t.fg;
      setFont(ctx, 36, 600);
      ctx.fillText(clip(ctx, it.name, 480), PAD + 64, ry + 56);
      const bx = PAD + 570;
      const bw = Math.max(14, ((W - PAD - bx - 150) * it.count) / max);
      ctx.fillStyle = t.accent;
      ctx.globalAlpha = 0.85;
      roundRectPath(ctx, bx, ry + 28, bw, 34, 6);
      ctx.fill();
      ctx.globalAlpha = 1;
      ctx.fillStyle = t.fg;
      setFont(ctx, 30, 600);
      ctx.fillText(`${it.count.toLocaleString()}회`, bx + bw + 14, ry + 56);
    });
    listBottom = ly + c.list.length * 84;
  }

  // 월별 청취 막대 그래프 (최근 36개월까지)
  if (c.monthly && c.monthly.months.length) {
    const months = c.monthly.months.slice(-36);
    const counts = c.monthly.counts.slice(-36);
    const top = Math.max(listBottom + 70, 1490);
    const base = H - PAD - 90;
    const hMax = Math.max(80, base - top - 60);
    ctx.fillStyle = t.sub;
    setFont(ctx, 30, 600);
    ctx.fillText(c.monthly.months.length > 36 ? "월별 청취 (최근 36개월)" : "월별 청취", PAD, top);
    const max = Math.max(1, ...counts);
    const bw = (W - 2 * PAD) / months.length;
    counts.forEach((v, i) => {
      const bh = v === 0 ? 3 : Math.max(6, (v / max) * hMax);
      ctx.fillStyle = v === 0 ? t.sub : t.accent;
      ctx.globalAlpha = v === 0 ? 0.35 : 0.9;
      ctx.fillRect(PAD + i * bw + 1.5, base - bh, Math.max(2, bw - 3), bh);
    });
    ctx.globalAlpha = 1;
    setFont(ctx, 26, 400);
    ctx.fillStyle = t.sub;
    ctx.fillText(months[0], PAD, base + 38);
    ctx.textAlign = "right";
    ctx.fillText(months[months.length - 1], W - PAD, base + 38);
    ctx.textAlign = "left";
  }
  footer(ctx, t);
}

// ---------------------------------------------------------------- 대화상자 / 공유 버튼

export type ShareSpec =
  | { kind: "period"; card: CardType; period?: Period; cat?: Cat; metric?: Metric }
  | { kind: "album"; name: string; artist: string | null }
  | { kind: "artist"; name: string }
  | { kind: "track"; name: string; artist: string | null; album?: string | null };

const PERIOD_LABELS: [Period, string][] = [["all", "전체 기간"], ["year", "연간"], ["month", "월간"], ["week", "주간"]];
const CARD_LABELS: [CardType, string][] = [["summary", "요약"], ["top", "Top 순위"], ["clock", "청취 시계"]];

const pill = (active: boolean) => ({ padding: "0.35rem 0.9rem", fontWeight: active ? 700 : 400, border: active ? "2px solid #8884d8" : "1px solid #666" });

let usernameMemo: Promise<string | null> | null = null;
const fetchUsername = () => {
  if (!usernameMemo) {
    usernameMemo = fetch(`${BASE_URL}/api/me`)
      .then((r) => r.json())
      .then((d) => (d.username as string | null) ?? null)
      .catch(() => null);
  }
  return usernameMemo;
};

function ShareDialog({ spec, onClose }: { spec: ShareSpec; onClose: () => void }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const isPeriod = spec.kind === "period";
  const [period, setPeriod] = useState<Period>(spec.kind === "period" ? spec.period ?? "month" : "all");
  const [periods, setPeriods] = useState<PeriodOption[]>([]);
  const [anchor, setAnchor] = useState<string>("");
  const [card, setCard] = useState<CardType>(spec.kind === "period" ? spec.card : "summary");
  const [cat, setCat] = useState<Cat>(spec.kind === "period" ? spec.cat ?? "artist" : "artist");
  const [metric, setMetric] = useState<Metric>(spec.kind === "period" ? spec.metric ?? "plays" : "plays");
  const [themeId, setThemeId] = useState("dark");
  const [report, setReport] = useState<Report | null>(null);
  const [subject, setSubject] = useState<SubjectCard | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [drawing, setDrawing] = useState(false);

  useEffect(() => {
    fetchUsername().then(setUsername);
  }, []);

  // ESC 로 닫기, 열려 있는 동안 뒤 화면 스크롤 막기
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  // 기간 목록 (기간 카드이고 전체 기간이 아닐 때)
  useEffect(() => {
    if (!isPeriod || period === "all") {
      setPeriods([]);
      setAnchor("");
      return;
    }
    let cancelled = false;
    fetch(`${BASE_URL}/api/ai-prompt/periods?period=${period}`)
      .then((res) => res.json())
      .then((d) => {
        if (cancelled || d.error) return;
        const list = d.periods as PeriodOption[];
        setPeriods(list);
        // 기본값: 마지막으로 끝난 기간 (진행 중·일부만 있는 기간이 아니면 그 기간, 없으면 가장 최근)
        setAnchor((list.find((p) => !p.partial) ?? list[0])?.key ?? "");
      })
      .catch((e) => setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [isPeriod, period]);

  // 카드 데이터: 기간 카드는 리포트, 앨범·아티스트·곡 카드는 해당 상세 정보
  useEffect(() => {
    let cancelled = false;
    setError(null);
    const fail = (e: Error) => !cancelled && setError(e.message);
    if (spec.kind === "period") {
      if (period !== "all" && !anchor) return;
      fetch(`${BASE_URL}/api/report-card?period=${period}${period !== "all" ? `&anchor=${encodeURIComponent(anchor)}` : ""}`)
        .then((res) => res.json())
        .then((d) => {
          if (cancelled) return;
          if (d.error) {
            setReport(null);
            setError(d.error);
          } else setReport(d as Report);
        })
        .catch(fail);
    } else {
      const q = new URLSearchParams({ name: spec.name });
      if (spec.kind !== "artist" && spec.artist) q.set("artist", spec.artist);
      if (spec.kind === "track") {
        q.set("limit", "1");
        if (spec.album) q.set("album", spec.album);
      }
      fetch(`${BASE_URL}/api/library/${spec.kind}?${q}`)
        .then((res) => res.json())
        .then((d) => {
          if (cancelled) return;
          if (d.error) return setError(d.error);
          setSubject(spec.kind === "album" ? normalizeAlbum(d) : spec.kind === "artist" ? normalizeArtist(d) : normalizeTrack(d));
        })
        .catch(fail);
    }
    return () => {
      cancelled = true;
    };
  }, [spec, period, anchor]);

  // 그리기
  const ready = isPeriod ? report : subject;
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !ready) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const theme = THEMES.find((t) => t.id === themeId) ?? THEMES[0];
    let cancelled = false;
    setDrawing(true);
    (async () => {
      // 1) 이미지 받기 (여기까지는 다른 요청이 끼어들어도 괜찮다)  2) 취소되지 않았을 때만 await 없이 한 번에 그린다
      if (isPeriod && report) {
        const images = card === "summary" ? await loadSummaryAssets(report) : card === "top" ? await loadTopAssets(report, cat, metric) : [];
        if (cancelled) return;
        if (card === "summary") drawSummary(ctx, report, theme, images);
        else if (card === "top") drawTop(ctx, report, theme, cat, metric, images);
        else drawClock(ctx, report, theme, metric);
      } else if (subject) {
        const image = await loadSubjectAssets(subject);
        if (cancelled) return;
        drawSubject(ctx, subject, theme, username, image);
      }
      setDrawing(false);
    })();
    return () => {
      cancelled = true;
    };
  }, [isPeriod, ready, report, subject, card, cat, metric, themeId, username]);

  const handleDownload = () => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    canvas.toBlob((blob) => {
      if (!blob) return;
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `analyse-your-music_${isPeriod ? `${card}_${period}${anchor ? "_" + anchor : ""}` : subject?.fileKey ?? spec.kind}.png`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }, "image/png");
  };

  const row = { display: "flex", gap: "0.5rem", flexWrap: "wrap" as const, justifyContent: "center", alignItems: "center" };
  return (
    <div
      onClick={(e) => e.target === e.currentTarget && onClose()}
      style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.72)", zIndex: 1000, overflowY: "auto", display: "flex", justifyContent: "center", alignItems: "flex-start", padding: "24px 12px" }}
    >
      <div role="dialog" aria-label="공유 이미지" style={{ background: "#1c1d23", color: "#eee", borderRadius: 12, padding: "1rem 1.2rem 1.4rem", width: "min(100%, 560px)", boxShadow: "0 8px 40px rgba(0,0,0,0.6)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "0.6rem" }}>
          <h3 style={{ margin: 0 }}>공유 이미지</h3>
          <button onClick={onClose} style={{ padding: "0.3rem 0.7rem" }} aria-label="닫기">
            ✕ 닫기
          </button>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: "0.7rem", alignItems: "center", marginBottom: "1rem" }}>
          {spec.kind === "period" && (
            <>
              <div style={row}>
                {CARD_LABELS.map(([c, text]) => (
                  <button key={c} onClick={() => setCard(c)} style={pill(card === c)}>
                    {text}
                  </button>
                ))}
              </div>
              <div style={row}>
                {PERIOD_LABELS.map(([p, text]) => (
                  <button key={p} onClick={() => setPeriod(p)} style={pill(period === p)}>
                    {text}
                  </button>
                ))}
                {period !== "all" && periods.length > 0 && (
                  <select value={anchor} onChange={(e) => setAnchor(e.target.value)}>
                    {periods.map((p) => (
                      <option key={p.key} value={p.key}>
                        {p.label} ({p.scrobbles.toLocaleString()}회{p.partial ? " · 일부 기간" : ""})
                      </option>
                    ))}
                  </select>
                )}
              </div>
              {card === "top" && (
                <div style={row}>
                  {(["artist", "album", "track"] as Cat[]).map((c) => (
                    <button key={c} onClick={() => setCat(c)} style={pill(cat === c)}>
                      {c === "artist" ? "아티스트" : c === "album" ? "앨범" : "트랙"}
                    </button>
                  ))}
                </div>
              )}
              {card !== "summary" && (
                <div style={row}>
                  {([["plays", "재생 횟수"], ["time", "청취 시간"]] as [Metric, string][]).map(([m, text]) => (
                    <button key={m} onClick={() => setMetric(m)} style={pill(metric === m)}>
                      {text}
                    </button>
                  ))}
                </div>
              )}
            </>
          )}
          <div style={{ ...row, gap: "0.6rem" }}>
            {THEMES.map((t) => (
              <button
                key={t.id}
                aria-label={`색상 ${t.id}`}
                title={t.id}
                onClick={() => setThemeId(t.id)}
                style={{
                  width: 32,
                  height: 32,
                  borderRadius: "50%",
                  padding: 0,
                  background: t.bg,
                  border: `3px solid ${t.border ?? t.bg}`,
                  outline: themeId === t.id ? "3px solid #8884d8" : "none",
                  outlineOffset: 2,
                  cursor: "pointer",
                }}
              />
            ))}
          </div>
        </div>

        {error && <p style={{ color: "#d66", textAlign: "center" }}>{error}</p>}
        {!ready && !error && <p style={{ color: "#999", textAlign: "center" }}>불러오는 중...</p>}

        <div style={{ display: ready ? "flex" : "none", flexDirection: "column", alignItems: "center", gap: "1rem" }}>
          <canvas
            ref={canvasRef}
            width={W}
            height={H}
            style={{ width: "min(100%, 340px)", height: "auto", aspectRatio: `${W} / ${H}`, borderRadius: 6, boxShadow: "0 2px 14px rgba(0,0,0,0.4)", opacity: drawing ? 0.6 : 1 }}
          />
          <button onClick={handleDownload} disabled={!ready || drawing} style={{ padding: "0.6rem 1.6rem", fontWeight: 700 }}>
            ⬇ PNG 다운로드 (1080×1920)
          </button>
        </div>
      </div>
    </div>
  );
}

const ShareContext = createContext<(spec: ShareSpec) => void>(() => {});

// 앱 전체를 감싸서 어디서든 useShare()/ShareButton 으로 공유 대화상자를 열 수 있게 한다
export function ShareProvider({ children }: { children: ReactNode }) {
  const [spec, setSpec] = useState<ShareSpec | null>(null);
  return (
    <ShareContext.Provider value={setSpec}>
      {children}
      {spec && <ShareDialog key={JSON.stringify(spec)} spec={spec} onClose={() => setSpec(null)} />}
    </ShareContext.Provider>
  );
}

export const useShare = () => useContext(ShareContext);

export function ShareButton({ spec, label = "🖼 공유 이미지", title = "이미지로 저장" }: { spec: ShareSpec; label?: string; title?: string }) {
  const open = useShare();
  return (
    <button onClick={() => open(spec)} title={title} style={{ padding: "0.3rem 0.8rem", fontSize: "0.85rem" }}>
      {label}
    </button>
  );
}
