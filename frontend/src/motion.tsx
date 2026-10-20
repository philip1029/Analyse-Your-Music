import { useEffect, useRef, useState, type CSSProperties } from "react";

// Apple Music 리플레이식 움직임: 숫자는 이전 값에서 새 값으로 굴러가고, 문장·목록은 아래에서 살짝 떠오르며 또렷해진다.
// 움직임 줄이기 설정(prefers-reduced-motion)이면 모두 즉시 바뀐다. CSS 는 index.css 의 aym-* 클래스.

export function prefersReducedMotion(): boolean {
  try {
    return window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  } catch {
    return false;
  }
}

const easeOutCubic = (t: number) => 1 - Math.pow(1 - t, 3);

// 처음에는 0 에서, 값이 바뀌면 지금 보이는 값에서 새 값까지 굴러간다
export function useCountUp(target: number, duration = 800): number {
  const [shown, setShown] = useState(() => (prefersReducedMotion() ? target : 0));
  const current = useRef(shown);
  current.current = shown;

  useEffect(() => {
    if (prefersReducedMotion() || !Number.isFinite(target)) {
      setShown(target);
      return;
    }
    const from = current.current;
    if (from === target) return;
    const start = performance.now();
    let raf = 0;
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / duration);
      setShown(from + (target - from) * easeOutCubic(t));
      if (t < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, duration]);

  return shown;
}

// 굴러가는 숫자. format 으로 "3,211시간 53분" 같은 표기를 줄 수 있다 (자릿수가 흔들리지 않게 고정폭 숫자)
export function Num({
  value,
  format = (n: number) => Math.round(n).toLocaleString(),
  duration,
}: {
  value: number;
  format?: (n: number) => string;
  duration?: number;
}) {
  const shown = useCountUp(value, duration);
  return <span style={{ fontVariantNumeric: "tabular-nums" }}>{format(shown)}</span>;
}

// 불러오는 동안 보여 줄 빛이 지나가는 자리 표시 막대
export function Skeleton({ lines = 3, height = 18, style }: { lines?: number; height?: number; style?: CSSProperties }) {
  return (
    <div aria-busy="true" aria-label="불러오는 중" style={{ display: "grid", gap: "0.7rem", ...style }}>
      {Array.from({ length: lines }, (_, i) => (
        <div key={i} className="aym-skeleton" style={{ height, width: `${92 - ((i * 17) % 38)}%` }} />
      ))}
    </div>
  );
}

// 목록 한 줄이 순서대로 떠오르게 하는 지연 값 (뒤쪽 항목이 너무 오래 기다리지 않도록 상한을 둔다)
export function stagger(i: number, step = 28, max = 420): CSSProperties {
  return { animationDelay: `${Math.min(i * step, max)}ms` };
}
