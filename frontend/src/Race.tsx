import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { BASE_URL } from "./config";
import { LINE } from "./RankRow";
import { cover } from "./Share";
import { tagEmoji } from "./tagEmoji";
import { MUTED } from "./theme";

// Bar chart race: 기간(월/주)이 흘러가면서 누적 재생 순위가 바뀌는 모습을 canvas 로 그린다 (막대가 자라고 순위가 휙휙 바뀐다).
// 같은 canvas 를 MediaRecorder 로 녹화해서 영상(mp4/webm)으로 저장할 수 있다. 서버는 기간별 누적 값만 주고, 기간 사이 보간과 순위 정렬은 여기서 한다.

type Cat = "artist" | "album" | "track" | "tag";
type Step = "month" | "week" | "day";
type Mode = "cumulative" | "rolling";
type Entity = { key: string; name: string; artist: string | null; album: string | null; album_artist: string | null; values: number[] };
type Avatar = "auto" | "photo" | "album";
type RaceData = { error?: string; cat: Cat; step: Step; window: number; periods: { label: string; date: string }[]; entities: Entity[]; total_plays: number; coverage: number | null };
type Ratio = "9:16" | "4:5";

const W = 1080;
const HEIGHT: Record<Ratio, number> = { "9:16": 1920, "4:5": 1350 };
const FONT = '"Apple SD Gothic Neo","Pretendard","Noto Sans KR",system-ui,sans-serif';
const EMOJI_FONT = '"Apple Color Emoji","Segoe UI Emoji","Noto Color Emoji",sans-serif';
const PALETTE = ["#ff7f50", "#4aa3ff", "#61d4b6", "#c490ff", "#ffcf5c", "#ff6b9a", "#7bd96a", "#f08a4b", "#5fd0e8", "#b5a3ff", "#e86a6a", "#9ad14b"];
const CAT_LABEL: Record<Cat, string> = { artist: "아티스트", album: "앨범", track: "트랙", tag: "장르/태그" };
const PERIODS_PER_SEC: Record<Step, number> = { month: 1.1, week: 5, day: 14 };
const ROLL_DAYS = 30;               // "최근 30일" 모드: 하루씩 넘기면서 그날까지 최근 30일의 값으로 순위를 매긴다
const HOLD_SECONDS = 2;           // 끝나고 마지막 순위를 보여 주는 시간
const MIN_SPEED = 0.05;           // 속도 슬라이더 범위 (로그 눈금: 느린 쪽을 촘촘하게)
const MAX_SPEED = 8;
const SPEED_PRESETS = [0.1, 0.25, 0.5, 1, 2, 4];
const SLOW_LEVELS = [{ min: 0.5, label: "약하게 (50%)" }, { min: 0.25, label: "보통 (25%)" }, { min: 0.1, label: "강하게 (10%)" }];   // 1위 교체 순간의 최저 속도
const DEFAULT_SLOW = 0.25;
const fmtSpeed = (x: number) => `${x < 1 ? x.toFixed(2).replace(/0$/, "") : x < 10 ? x.toFixed(1).replace(/\.0$/, "") : x.toFixed(0)}x`;
const THEMES = {
  dark: { bg: "#121214", fg: "#ffffff", sub: "#9a9aa2", track: "rgba(255,255,255,0.07)", ghost: "rgba(255,255,255,0.09)" },
  light: { bg: "#ffffff", fg: "#111111", sub: "#6b6b73", track: "rgba(0,0,0,0.06)", ghost: "rgba(0,0,0,0.07)" },
};
type ThemeId = keyof typeof THEMES;

const ease = (f: number) => f * f * (3 - 2 * f);
const lerp = (a: number, b: number, f: number) => a + (b - a) * f;

function periodText(step: Step, p: { label: string; date: string }): string {
  const [y, m, d] = p.date.split("-");
  return step === "month" ? `${y}.${m}` : `${y}.${m}.${d}`;
}

function fitText(ctx: CanvasRenderingContext2D, text: string, maxW: number, size: number, weight: number | string, min = 20): number {
  let s = size;
  ctx.font = `${weight} ${s}px ${FONT}`;
  while (ctx.measureText(text).width > maxW && s > min) {
    s -= 2;
    ctx.font = `${weight} ${s}px ${FONT}`;
  }
  return s;
}

function ellipsize(ctx: CanvasRenderingContext2D, text: string, maxW: number): string {
  if (ctx.measureText(text).width <= maxW) return text;
  let t = text;
  while (t.length > 1 && ctx.measureText(t + "…").width > maxW) t = t.slice(0, -1);
  return t + "…";
}

// 1위가 오래 지킨 자리에서 바뀌는 프레임 번호들 (화면의 "새 1위" 강조와 같은 기준). 슬로우 모션이 이 순간 앞뒤로 시간을 늦춘다.
function leaderEvents(race: RaceData): number[] {
  const minHold = Math.max(1, Math.round(PERIODS_PER_SEC[race.step] * 0.8));
  const out: number[] = [];
  let prev = -1;
  let held = 0;
  for (let p = 0; p < race.periods.length; p++) {
    let best = -1;
    let bv = 0;
    race.entities.forEach((e, i) => {
      const v = e.values[p];
      if (v > bv || (v === bv && v > 0 && best >= 0 && e.key < race.entities[best].key)) {
        bv = v;
        best = i;
      }
    });
    if (best < 0) continue;
    if (prev >= 0 && best !== prev) {
      if (held >= minHold) out.push(p);
      held = 0;
    } else {
      held++;
    }
    prev = best;
  }
  return out;
}

// 1위 교체 순간(events)에 가까울수록 느려지는 시간 배율 (1 = 보통, slowMin = 교체 순간의 가장 느린 속도)
function slowFactor(events: number[], t: number, rate: number, slowMin: number): number {
  const reach = rate * 1.3;                                          // 앞뒤로 약 1.3초 구간
  let w = 0;
  for (const e of events) {
    if (e - t > reach) break;
    w = Math.max(w, 1 - Math.abs(e - t) / reach);
  }
  return 1 - (1 - slowMin) * ease(Math.max(0, w));
}

type View = {
  race: RaceData;
  topN: number;
  ratio: Ratio;
  theme: ThemeId;
  title: string;
  images: Map<string, HTMLImageElement | null>;
  colors: Map<string, string>;
  useCover: boolean;
  ys: Map<string, number>;
  scale: { max: number };
  lead: { key: string | null; flash: number; held: number };   // 1위가 바뀌면 flash 가 1 로 올라가고 서서히 줄어든다 (held: 지금 1위가 자리를 지킨 시간)
};

// 커버 이미지에서 막대 색을 뽑는다: 채도가 높은 픽셀을 더 크게 반영하고, 어두운 배경에서 보이도록 너무 어두우면 밝힌다. 거의 무채색이면 null.
function dominantColor(img: HTMLImageElement): string | null {
  try {
    const c = document.createElement("canvas");
    c.width = c.height = 24;
    const g = c.getContext("2d", { willReadFrequently: true });
    if (!g) return null;
    g.drawImage(img, 0, 0, 24, 24);
    const d = g.getImageData(0, 0, 24, 24).data;
    let r = 0, gr = 0, b = 0, w = 0, satSum = 0;
    for (let i = 0; i < d.length; i += 4) {
      const R = d[i], G = d[i + 1], B = d[i + 2];
      const mx = Math.max(R, G, B), mn = Math.min(R, G, B);
      const sat = mx === 0 ? 0 : (mx - mn) / mx;
      const light = (mx + mn) / 510;
      const wt = sat * sat * (1 - Math.abs(light - 0.5) * 1.4) + 0.001;
      r += R * wt; gr += G * wt; b += B * wt; w += wt; satSum += sat;
    }
    if (!w || satSum / (d.length / 4) < 0.12) return null;
    // 평균 색의 색상(hue)만 가져와서 채도·밝기를 맞춘다 (평균을 내면 칙칙해지므로 어두운 배경에서도 선명하게)
    const R = r / w / 255, G = gr / w / 255, B = b / w / 255;
    const mx = Math.max(R, G, B), mn = Math.min(R, G, B), dlt = mx - mn;
    let h = 0;
    if (dlt > 0) h = mx === R ? ((G - B) / dlt) % 6 : mx === G ? (B - R) / dlt + 2 : (R - G) / dlt + 4;
    h = Math.round(((h * 60) + 360) % 360);
    const l0 = (mx + mn) / 2;
    const sat = dlt === 0 ? 0 : dlt / (1 - Math.abs(2 * l0 - 1));
    return `hsl(${h} ${Math.round(Math.min(85, Math.max(55, sat * 100)))}% 58%)`;
  } catch {
    return null;                                           // 이미지가 canvas 를 오염시켰거나 못 읽으면 기본 색
  }
}

// 한 프레임 그리기: t 는 기간 번호(소수). ys/scale 은 프레임마다 이어서 갱신되는 애니메이션 상태(순위 위치·축 길이)다.
function drawFrame(ctx: CanvasRenderingContext2D, v: View, t: number, dt: number) {
  const th = THEMES[v.theme];
  const H = HEIGHT[v.ratio];
  const { race, topN } = v;
  const last = race.periods.length - 1;
  const i = Math.min(Math.floor(t), last);
  const f = i >= last ? 0 : ease(t - i);

  ctx.fillStyle = th.bg;
  ctx.fillRect(0, 0, W, H);

  // 지금 시점의 값과 순위
  const cur = race.entities.map((e, idx) => ({ e, idx, val: lerp(e.values[i], e.values[Math.min(i + 1, last)], f) }));
  cur.sort((a, b) => b.val - a.val || (a.e.key < b.e.key ? -1 : 1));
  const top = cur[0]?.val || 1;
  const snap = race.window > 0;                                        // 롤링은 순위가 하루씩 착착 바뀌도록 위치 이동을 더 빠르게
  v.scale.max += (Math.max(top * 1.06, 1) - v.scale.max) * (1 - Math.exp(-dt * (snap ? 9 : 6)));
  const leadKey = cur[0] && cur[0].val > 0 ? cur[0].e.key : null;
  if (leadKey !== null && leadKey !== v.lead.key) {
    if (v.lead.key !== null && v.lead.held >= 0.8) v.lead.flash = 1;       // 1위가 하루 이틀 만에 오락가락하는 건 알리지 않는다 (0.8초 이상 지킨 1위가 바뀔 때만)
    v.lead.key = leadKey;
    v.lead.held = 0;
  } else {
    v.lead.held += dt;
  }
  v.lead.flash = Math.max(0, v.lead.flash - dt / 1.6);

  // 제목
  const headerH = 300;
  const footerH = v.ratio === "9:16" ? 210 : 150;
  ctx.textBaseline = "alphabetic";
  ctx.textAlign = "left";
  ctx.fillStyle = th.fg;
  fitText(ctx, v.title, W - 192, 58, 800, 34);
  ctx.fillText(v.title, 96, 150);
  ctx.fillStyle = th.sub;
  ctx.font = `500 34px ${FONT}`;
  const unit = race.cat === "tag" ? "태그 점수 (재생 수 × 태그 비중)" : "재생 수";
  ctx.fillText(race.window ? `최근 ${race.window}일 ${unit}` : `누적 ${unit}`, 96, 205);
  if (v.lead.flash > 0.02 && cur[0]) {                                  // 1위가 바뀌는 순간 잠깐 알린다
    ctx.globalAlpha = Math.min(1, v.lead.flash * 1.6);
    ctx.fillStyle = th.fg;
    fitText(ctx, `👑 새 1위 · ${cur[0].e.name}`, W - 192, 44, 800, 26);
    ctx.fillText(`👑 새 1위 · ${cur[0].e.name}`, 96, 262);
    ctx.globalAlpha = 1;
  }

  // 큰 기간 글자 (막대 뒤에 깔리는 워터마크)
  const label = periodText(race.step, race.periods[Math.min(Math.round(t), last)]);
  ctx.textAlign = "right";
  ctx.fillStyle = th.ghost;
  fitText(ctx, label, W - 160, v.ratio === "9:16" ? 190 : 160, 800, 60);      // 일·주 단위는 날짜(2024.06.02)가 길어서 폭에 맞춰 글자 크기를 줄인다
  ctx.fillText(label, W - 80, H - footerH - 24);

  // 막대들
  const area = H - headerH - footerH;
  const rowH = Math.min(area / topN, 170);
  const stacked = rowH >= 100;
  const barH = stacked ? Math.round(rowH * 0.5) : Math.round(rowH * 0.74);
  const nameW = stacked ? 0 : 290;
  const x0 = 96 + nameW;
  const avatar = barH + 18;
  const valueW = 170;
  const maxBarW = W - 96 - x0 - valueW - avatar / 2;

  cur.forEach((c, rank) => {
    const target = rank < topN ? rank : topN + 0.6;
    const prev = v.ys.get(c.e.key);
    const y0 = prev === undefined ? target : prev;                       // 처음 나타나는 개체는 목표 자리에서 바로 시작(아래에서 올라오지 않게)
    const y = y0 + (target - y0) * (1 - Math.exp(-dt * (snap ? 20 : 11)));
    v.ys.set(c.e.key, y);
    if (y > topN + 0.2 || c.val <= 0) return;                            // 화면 아래로 나간 막대는 그리지 않는다

    const color = (v.useCover && v.colors.get(c.e.key)) || PALETTE[c.idx % PALETTE.length];
    const top0 = headerH + y * rowH;
    const w = Math.max(barH, (c.val / v.scale.max) * maxBarW);
    const by = stacked ? top0 + rowH * 0.4 : top0 + (rowH - barH) / 2;
    const alpha = Math.max(0, Math.min(1, topN + 0.2 - y));

    ctx.globalAlpha = alpha;
    // 이름
    ctx.fillStyle = th.fg;
    if (stacked) {
      ctx.textAlign = "left";
      fitText(ctx, c.e.name, W - 192 - valueW, 40, 700, 24);
      ctx.fillText(ellipsize(ctx, c.e.name, W - 192 - valueW), 96, by - 12);
    } else {
      ctx.textAlign = "right";
      fitText(ctx, c.e.name, nameW - 20, 34, 700, 20);
      ctx.fillText(ellipsize(ctx, c.e.name, nameW - 20), x0 - 20, by + barH / 2 + 12);
    }
    // 막대
    ctx.fillStyle = th.track;
    ctx.beginPath();
    ctx.roundRect(x0, by, maxBarW + avatar / 2, barH, barH / 2);
    ctx.fill();
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.roundRect(x0, by, w, barH, barH / 2);
    ctx.fill();
    if (rank === 0 && v.lead.flash > 0.02) {
      ctx.lineWidth = 6;
      ctx.strokeStyle = th.fg;
      ctx.globalAlpha = alpha * Math.min(1, v.lead.flash * 1.6);
      ctx.stroke();
      ctx.globalAlpha = alpha;
    }
    // 값
    ctx.textAlign = "left";
    ctx.fillStyle = th.fg;
    ctx.font = `800 ${stacked ? 40 : 34}px ${FONT}`;
    ctx.fillText(Math.round(c.val).toLocaleString(), x0 + w + avatar / 2 + 18, by + barH / 2 + (stacked ? 14 : 12));
    // 아바타 (커버 이미지, 없으면 색 원 + 첫 글자)
    const cx = x0 + w - barH / 2 + 2;
    const cy = by + barH / 2;
    const r = avatar / 2;
    ctx.save();
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.closePath();
    ctx.clip();
    const img = v.images.get(c.e.key);
    if (img) {
      const s = Math.max((r * 2) / img.width, (r * 2) / img.height);
      ctx.drawImage(img, cx - (img.width * s) / 2, cy - (img.height * s) / 2, img.width * s, img.height * s);
    } else {
      ctx.fillStyle = race.cat === "tag" ? "#ffffff" : color;           // 이모지는 흰 바탕 위에 올린다
      ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
      ctx.textAlign = "center";
      if (race.cat === "tag") {                                          // 장르는 어울리는 이모지를 넣는다
        ctx.font = `${Math.round(r * 1.15)}px ${EMOJI_FONT}`;
        ctx.fillText(tagEmoji(c.e.name), cx, cy + r * 0.4);
      } else {
        ctx.fillStyle = "#111";
        ctx.font = `800 ${Math.round(r)}px ${FONT}`;
        ctx.fillText(Array.from(c.e.name)[0]?.toUpperCase() ?? "", cx, cy + r * 0.34);
      }
    }
    ctx.restore();
    ctx.lineWidth = 4;
    ctx.strokeStyle = th.bg;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
    ctx.globalAlpha = 1;
  });

  // 진행 막대와 서비스 이름
  const px = 96;
  const pw = W - 192;
  const py = H - footerH + 40;
  ctx.fillStyle = th.track;
  ctx.fillRect(px, py, pw, 8);
  ctx.fillStyle = th.fg;
  ctx.fillRect(px, py, (pw * Math.min(t, last)) / Math.max(last, 1), 8);
  ctx.textAlign = "right";
  ctx.fillStyle = th.sub;
  ctx.font = `600 34px ${FONT}`;
  ctx.fillText("Analyse Your Music", W - 96, H - 56);
  ctx.textAlign = "left";
}

const pill = (on: boolean): CSSProperties => ({
  padding: "0.25rem 0.8rem",
  borderRadius: 999,
  border: on ? "1px solid #ff7f50" : LINE,
  background: on ? "#ff7f50" : "transparent",
  color: on ? "#1a1b1e" : "inherit",
  fontWeight: on ? 700 : 500,
  fontSize: "0.85rem",
  cursor: "pointer",
});

export function RaceTab({ query }: { query: (extra?: Record<string, string | number>) => string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const scrubRef = useRef<HTMLInputElement>(null);
  const [mode, setMode] = useState<Mode>("cumulative");
  const [cat, setCat] = useState<Cat>("artist");
  const [stepChoice, setStep] = useState<Step>("month");
  const step: Step = mode === "rolling" ? "day" : stepChoice;
  const [coverColors, setCoverColors] = useState(true);
  const [avatar, setAvatar] = useState<Avatar>("auto");
  const [topN, setTopN] = useState(10);
  const [ratio, setRatio] = useState<Ratio>("9:16");
  const [themeId, setThemeId] = useState<ThemeId>("dark");
  const [speed, setSpeed] = useState(1);
  const [slowMo, setSlowMo] = useState(true);
  const [slowMin, setSlowMin] = useState(DEFAULT_SLOW);
  const [race, setRace] = useState<RaceData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [username, setUsername] = useState<string | null>(null);
  const [imagesLoaded, setImagesLoaded] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [recording, setRecording] = useState<string | null>(null);

  // 애니메이션 상태는 ref 에 둔다 (프레임마다 React 를 다시 그리지 않기 위해)
  const st = useRef({ t: 0, playing: false, speed: 1, slow: true, slowMin: DEFAULT_SLOW, events: [] as number[], last: 0, hold: 0, ys: new Map<string, number>(), scale: { max: 1 }, images: new Map<string, HTMLImageElement | null>(), colors: new Map<string, string>(), lead: { key: null as string | null, flash: 0, held: 0 }, recorder: null as null | { stop: () => void } });
  const view = useRef<View | null>(null);

  useEffect(() => {
    fetch(`${BASE_URL}/api/me`).then((r) => r.json()).then((d) => setUsername(d.username ?? null)).catch(() => undefined);
  }, []);

  // 데이터 받기
  useEffect(() => {
    let cancelled = false;
    setError(null);
    setRace(null);
    st.current.playing = false;
    setPlaying(false);
    fetch(`${BASE_URL}/api/race${query({ cat, step, top: topN, window: mode === "rolling" ? ROLL_DAYS : 0 })}`)
      .then((r) => r.json())
      .then((d: RaceData) => {
        if (cancelled) return;
        if (d.error) return setError(d.error);
        st.current.t = 0;
        st.current.ys = new Map();
        st.current.scale = { max: 1 };
        st.current.images = new Map();
        st.current.colors = new Map();
        st.current.lead = { key: null, flash: 0, held: 0 };
        st.current.events = leaderEvents(d);
        setRace(d);
      })
      .catch((e) => !cancelled && setError(e.message));
    return () => {
      cancelled = true;
    };
  }, [cat, step, topN, mode, query]);

  // 막대 끝 이미지 미리 받기 (몇 개씩 나눠서). 직접 올린 커버가 있으면 서버가 그것을 먼저 돌려준다.
  // 아티스트는 사진 -> (없으면) 가장 많이 들은 앨범 커버, 트랙은 앨범 커버 -> (없으면) 아티스트 사진이 기본이고, avatar 로 우선순위를 바꿀 수 있다.
  useEffect(() => {
    if (!race || race.cat === "tag") {
      setImagesLoaded(0);
      return;
    }
    let cancelled = false;
    const images = st.current.images;
    const colors = st.current.colors;
    images.clear();
    colors.clear();
    setImagesLoaded(0);
    const loadAvatar = async (e: Entity): Promise<HTMLImageElement | null> => {
      const photo = () => cover("artist", race.cat === "artist" ? e.name : e.artist);
      const album = () => (e.album ? cover("album", e.album_artist, e.album) : Promise.resolve(null));
      const order = race.cat === "album" ? [album] : avatar === "photo" ? [photo, album] : avatar === "album" ? [album, photo] : race.cat === "artist" ? [photo, album] : [album, photo];
      for (const load of order) {
        const img = await load();
        if (img) return img;
      }
      return null;
    };
    (async () => {
      let done = 0;
      const items = [...race.entities];
      for (let i = 0; i < items.length && !cancelled; i += 4) {
        await Promise.all(
          items.slice(i, i + 4).map(async (e) => {
            const img = await loadAvatar(e);
            if (cancelled) return;
            images.set(e.key, img);
            const col = img ? dominantColor(img) : null;
            if (col) colors.set(e.key, col);
            done++;
          })
        );
        if (!cancelled) setImagesLoaded(done);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [race, avatar]);

  // 보여 줄 값이 바뀔 때마다 view 갱신
  useEffect(() => {
    if (!race) {
      view.current = null;
      return;
    }
    const username0 = username ? `${username}의 ` : "";
    view.current = { race, topN, ratio, theme: themeId, title: `${username0}${CAT_LABEL[race.cat]} 랭킹`, images: st.current.images, colors: st.current.colors, useCover: coverColors, ys: st.current.ys, scale: st.current.scale, lead: st.current.lead };
  }, [race, topN, ratio, themeId, username, coverColors]);

  const finish = useCallback(() => {
    st.current.playing = false;
    setPlaying(false);
    const rec = st.current.recorder;
    if (rec) {
      st.current.recorder = null;
      rec.stop();
    }
  }, []);

  // 그리기 루프
  useEffect(() => {
    let raf = 0;
    const tick = (now: number) => {
      raf = requestAnimationFrame(tick);
      const canvas = canvasRef.current;
      const v = view.current;
      if (!canvas || !v) return;
      const s = st.current;
      const dt = Math.min((now - (s.last || now)) / 1000, 0.1);
      s.last = now;
      const last = v.race.periods.length - 1;
      if (s.playing) {
        const rate = PERIODS_PER_SEC[v.race.step];
        s.t += dt * rate * s.speed * (s.slow ? slowFactor(s.events, s.t, rate, s.slowMin) : 1);
        if (s.t >= last) {
          s.t = last;
          s.hold += dt;
          if (s.hold >= HOLD_SECONDS) finish();
        }
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      drawFrame(ctx, v, s.t, s.playing || s.hold ? dt : 0.5);
      if (scrubRef.current) scrubRef.current.value = String(s.t);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [finish]);

  useEffect(() => {
    const c = canvasRef.current;
    if (c) {
      c.width = W;
      c.height = HEIGHT[ratio];
    }
  }, [ratio]);

  const play = () => {
    const s = st.current;
    if (!race) return;
    if (s.t >= race.periods.length - 1) {
      s.t = 0;
      s.ys.clear();
      s.scale.max = 1;
      s.lead.key = null;
      s.lead.flash = 0;
      s.lead.held = 0;
    }
    s.hold = 0;
    s.playing = true;
    setPlaying(true);
  };
  const pause = () => {
    st.current.playing = false;
    setPlaying(false);
  };
  const restart = () => {
    const s = st.current;
    s.t = 0;
    s.hold = 0;
    s.lead.key = null;
    s.lead.flash = 0;
    s.lead.held = 0;
    s.ys.clear();
    s.scale.max = 1;
  };

  const record = () => {
    const canvas = canvasRef.current;
    if (!canvas || !race || typeof MediaRecorder === "undefined") {
      setRecording("이 브라우저는 영상 저장을 지원하지 않아요.");
      return;
    }
    const type = ["video/mp4;codecs=avc1", "video/mp4", "video/webm;codecs=vp9", "video/webm"].find((t) => MediaRecorder.isTypeSupported(t)) ?? "";
    const ext = type.startsWith("video/mp4") ? "mp4" : "webm";
    const chunks: Blob[] = [];
    const recorder = new MediaRecorder(canvas.captureStream(30), { ...(type ? { mimeType: type } : {}), videoBitsPerSecond: 8_000_000 });
    recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
    recorder.onstop = () => {
      const blob = new Blob(chunks, { type: type || "video/webm" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `analyse-your-music_race_${race.cat}_${race.step}.${ext}`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      setRecording(`저장했어요 (${ext}, ${(blob.size / 1e6).toFixed(1)}MB)${ext === "webm" ? " — 인스타그램은 mp4 만 받아서 변환이 필요해요 (예: ffmpeg -i 파일.webm 파일.mp4)" : ""}`);
    };
    setRecording("녹화 중… 끝까지 재생되면 자동으로 저장돼요");
    restart();
    recorder.start(250);
    st.current.recorder = { stop: () => recorder.stop() };
    play();
  };

  const stopRecording = () => {
    st.current.recorder?.stop();
    st.current.recorder = null;
    pause();
  };

  const periods = race?.periods.length ?? 0;
  return (
    <section style={{ textAlign: "left" }}>
      <h2 style={{ marginBottom: "0.3rem" }}>Race <span style={{ color: MUTED, fontSize: "0.9rem", fontWeight: 500 }}>누적 순위가 바뀌는 모습</span></h2>
      <p style={{ color: MUTED, fontSize: "0.85rem", margin: "0 0 0.8rem" }}>
        시간이 흐르면서 순위가 휙휙 바뀌는 영상을 만들어요. 누적은 달(또는 주)마다 값을 쌓고, 최근 30일은 하루씩 넘기면서 그날까지 30일 동안의 값으로 순위를 매겨 착착 바뀝니다. 위쪽에서 고른 기간 안에서 계산해요.
      </p>

      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "center", marginBottom: "0.5rem" }}>
        <button type="button" onClick={() => setMode("cumulative")} style={pill(mode === "cumulative")}>누적</button>
        <button type="button" onClick={() => setMode("rolling")} style={pill(mode === "rolling")} title="하루씩 넘기면서, 그날까지 최근 30일 동안의 값으로 순위를 매깁니다">최근 30일 (하루씩)</button>
        <span style={{ width: 12 }} />
        {(Object.keys(CAT_LABEL) as Cat[]).map((c) => (
          <button key={c} type="button" onClick={() => setCat(c)} style={pill(cat === c)}>{CAT_LABEL[c]}</button>
        ))}
        <span style={{ width: 12 }} />
        {mode === "cumulative" && (
          <>
            <button type="button" onClick={() => setStep("month")} style={pill(stepChoice === "month")}>월별</button>
            <button type="button" onClick={() => setStep("week")} style={pill(stepChoice === "week")}>주별</button>
            <span style={{ width: 12 }} />
          </>
        )}
        <label style={{ fontSize: "0.85rem", color: MUTED }}>
          상위{" "}
          <select value={topN} onChange={(e) => setTopN(Number(e.target.value))} style={{ background: "transparent", color: "inherit", border: LINE, borderRadius: 6, padding: "0.2rem" }}>
            {[5, 8, 10, 12, 15].map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
        <label style={{ fontSize: "0.85rem", color: MUTED }}>
          비율{" "}
          <select value={ratio} onChange={(e) => setRatio(e.target.value as Ratio)} style={{ background: "transparent", color: "inherit", border: LINE, borderRadius: 6, padding: "0.2rem" }}>
            <option value="9:16">9:16 (릴스·스토리)</option>
            <option value="4:5">4:5 (피드)</option>
          </select>
        </label>
        {(cat === "artist" || cat === "track") && (
          <label style={{ fontSize: "0.85rem", color: MUTED }}>
            이미지{" "}
            <select value={avatar} onChange={(e) => setAvatar(e.target.value as Avatar)} style={{ background: "transparent", color: "inherit", border: LINE, borderRadius: 6, padding: "0.2rem" }}>
              <option value="auto">{cat === "artist" ? "자동 (사진, 없으면 앨범)" : "자동 (앨범, 없으면 사진)"}</option>
              <option value="photo">아티스트 사진 우선</option>
              <option value="album">앨범 커버 우선</option>
            </select>
          </label>
        )}
        <label style={{ fontSize: "0.85rem", color: MUTED }}>
          막대 색{" "}
          <select value={coverColors ? "cover" : "palette"} onChange={(e) => setCoverColors(e.target.value === "cover")} style={{ background: "transparent", color: "inherit", border: LINE, borderRadius: 6, padding: "0.2rem" }}>
            <option value="cover">커버 색</option>
            <option value="palette">기본 색</option>
          </select>
        </label>
        <label style={{ fontSize: "0.85rem", color: MUTED }}>
          배경{" "}
          <select value={themeId} onChange={(e) => setThemeId(e.target.value as ThemeId)} style={{ background: "transparent", color: "inherit", border: LINE, borderRadius: 6, padding: "0.2rem" }}>
            <option value="dark">어둡게</option>
            <option value="light">밝게</option>
          </select>
        </label>
      </div>

      {error && <p style={{ color: "#e07070" }}>{error}</p>}
      {race && race.entities.length === 0 && <p style={{ color: MUTED }}>이 기간에는 보여 줄 기록이 없어요.{race.cat === "tag" ? " (아티스트 태그가 아직 없다면 Data 탭에서 먼저 채워 주세요)" : ""}</p>}

      <div style={{ display: "flex", gap: "1.2rem", flexWrap: "wrap", alignItems: "flex-start" }}>
        <canvas
          ref={canvasRef}
          width={W}
          height={HEIGHT[ratio]}
          style={{ width: "min(100%, 400px)", height: "auto", aspectRatio: `${W} / ${HEIGHT[ratio]}`, borderRadius: 10, border: LINE, background: "#121214" }}
        />
        <div style={{ flex: 1, minWidth: 240, display: "flex", flexDirection: "column", gap: "0.7rem" }}>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {playing ? (
              <button type="button" onClick={pause} style={pill(true)}>⏸ 일시정지</button>
            ) : (
              <button type="button" onClick={play} disabled={!race || race.entities.length === 0} style={pill(true)}>▶ 재생</button>
            )}
            <button type="button" onClick={restart} style={pill(false)}>⏮ 처음부터</button>
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: "0.35rem" }}>
            <label style={{ fontSize: "0.85rem", color: MUTED, display: "flex", alignItems: "center", gap: "0.6rem" }}>
              속도
              <input
                type="range"
                min={Math.log2(MIN_SPEED)}
                max={Math.log2(MAX_SPEED)}
                step={0.01}
                value={Math.log2(speed)}
                aria-label="재생 속도"
                onChange={(e) => {
                  const x = Math.round(2 ** Number(e.target.value) * 100) / 100;
                  setSpeed(x);
                  st.current.speed = x;
                }}
                style={{ flex: 1 }}
              />
              <strong style={{ color: "CanvasText", minWidth: 48, textAlign: "right" }}>{fmtSpeed(speed)}</strong>
            </label>
            <div style={{ display: "flex", gap: "0.35rem", flexWrap: "wrap" }}>
              {SPEED_PRESETS.map((x) => (
                <button key={x} type="button" onClick={() => { setSpeed(x); st.current.speed = x; }} style={{ ...pill(Math.abs(speed - x) < 0.005), padding: "0.15rem 0.6rem", fontSize: "0.8rem" }}>{fmtSpeed(x)}</button>
              ))}
            </div>
            <label style={{ fontSize: "0.85rem", color: MUTED, display: "flex", alignItems: "center", gap: "0.4rem" }}>
              <input type="checkbox" checked={slowMo} onChange={(e) => { setSlowMo(e.target.checked); st.current.slow = e.target.checked; }} />
              슬로우 모션 (1위가 바뀌는 순간 앞뒤로 느려져요)
              <select
                value={slowMin}
                disabled={!slowMo}
                aria-label="슬로우 정도"
                onChange={(e) => { const x = Number(e.target.value); setSlowMin(x); st.current.slowMin = x; }}
                style={{ background: "transparent", color: "inherit", border: LINE, borderRadius: 6, padding: "0.15rem" }}
              >
                {SLOW_LEVELS.map((l) => <option key={l.min} value={l.min}>{l.label}</option>)}
              </select>
            </label>
          </div>
          <input
            ref={scrubRef}
            type="range"
            min={0}
            max={Math.max(periods - 1, 0)}
            step={0.01}
            defaultValue={0}
            aria-label="시점"
            onChange={(e) => {
              st.current.t = Number(e.target.value);
              st.current.hold = 0;
            }}
            style={{ width: "100%" }}
          />
          <div style={{ display: "flex", gap: "0.6rem", alignItems: "center", flexWrap: "wrap" }}>
            {st.current.recorder || (recording && recording.startsWith("녹화")) ? (
              <button type="button" onClick={stopRecording} style={pill(false)}>⏹ 녹화 중단</button>
            ) : (
              <button type="button" onClick={record} disabled={!race || race.entities.length === 0} style={pill(false)}>🎬 영상으로 저장</button>
            )}
          </div>
          {recording && <p style={{ color: MUTED, fontSize: "0.85rem", margin: 0 }}>{recording}</p>}
          <p style={{ color: MUTED, fontSize: "0.8rem", margin: 0 }}>
            {race ? `${periods}개 ${race.step === "month" ? "월" : race.step === "week" ? "주" : "일"} · 개체 ${race.entities.length}개` : "불러오는 중…"}
            {race && race.cat !== "tag" ? ` · 이미지 ${imagesLoaded}/${race.entities.length}` : ""}
            {race && race.cat === "tag" && race.coverage !== null ? ` · 태그가 있는 아티스트의 재생만 반영 (${Math.round(race.coverage * 100)}%)` : ""}
          </p>
        </div>
      </div>
    </section>
  );
}
