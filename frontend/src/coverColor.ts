// 커버 이미지에서 대표 색을 뽑는다 (Race 막대 색, 요약 TOP 카드 배경색이 함께 쓴다).
// 이미지는 canvas 가 오염되지 않는 것(Share.tsx 의 cover(): 프록시 경유)이어야 한다.

function rgbToHsl(r: number, g: number, b: number): [number, number, number] {
  const R = r / 255, G = g / 255, B = b / 255;
  const mx = Math.max(R, G, B), mn = Math.min(R, G, B), d = mx - mn;
  const l = (mx + mn) / 2;
  const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
  let h = 0;
  if (d > 0) h = mx === R ? ((G - B) / d) % 6 : mx === G ? (B - R) / d + 2 : (R - G) / d + 4;
  return [((h * 60) + 360) % 360, s, l];
}

// 커버 이미지에서 막대 색을 뽑는다. 색이 있는 픽셀(채도 22% 이상, 너무 밝거나 어둡지 않은)을 색상(hue) 24칸에 모아 가장 많이 쌓인 색상 둘레를 쓴다
// (평균을 내면 파랑+주황이 섞여 엉뚱한 색이 되기 때문). 색 있는 픽셀이 4% 미만인 무채색 커버(흰 바탕·흑백 등)는 커버의 평균 색을 연한 회색 톤으로 쓴다.
export function dominantColor(img: HTMLImageElement): string | null {
  try {
    const N = 32;
    const c = document.createElement("canvas");
    c.width = c.height = N;
    const g = c.getContext("2d", { willReadFrequently: true });
    if (!g) return null;
    g.drawImage(img, 0, 0, N, N);
    const d = g.getImageData(0, 0, N, N).data;
    const BINS = 24;
    const wsum = new Array<number>(BINS).fill(0);
    const sums = Array.from({ length: BINS }, () => [0, 0, 0, 0]);   // r, g, b, weight
    let colored = 0, ar = 0, ag = 0, ab = 0;
    for (let i = 0; i < d.length; i += 4) {
      const R = d[i], G = d[i + 1], B = d[i + 2];
      ar += R; ag += G; ab += B;
      const [h, s, l] = rgbToHsl(R, G, B);
      if (s >= 0.22 && l > 0.15 && l < 0.9) {
        colored++;
        const w = s * Math.max(0.05, 1 - Math.abs(l - 0.5) * 1.2);
        const bin = Math.floor((h / 360) * BINS) % BINS;
        wsum[bin] += w;
        sums[bin][0] += R * w; sums[bin][1] += G * w; sums[bin][2] += B * w; sums[bin][3] += w;
      }
    }
    const px = d.length / 4;
    if (colored / px >= 0.04) {
      let best = 0, bestScore = -1;
      for (let b = 0; b < BINS; b++) {
        const score = wsum[b] + 0.5 * (wsum[(b + BINS - 1) % BINS] + wsum[(b + 1) % BINS]);
        if (score > bestScore) { bestScore = score; best = b; }
      }
      let r = 0, gr = 0, bl = 0, w = 0;
      for (const b of [best - 1, best, best + 1]) {
        const q = sums[(b + BINS) % BINS];
        r += q[0]; gr += q[1]; bl += q[2]; w += q[3];
      }
      const [h, s] = rgbToHsl(r / w, gr / w, bl / w);
      return `hsl(${Math.round(h)} ${Math.round(Math.min(0.85, Math.max(0.5, s)) * 100)}% 58%)`;
    }
    const [h, s, l] = rgbToHsl(ar / px, ag / px, ab / px);
    return `hsl(${Math.round(h)} ${Math.round(Math.min(0.15, s) * 100)}% ${Math.round(Math.min(0.8, Math.max(0.55, l)) * 100)}%)`;
  } catch {
    return null;                                           // 이미지가 canvas 를 오염시켰거나 못 읽으면 기본 색
  }
}
