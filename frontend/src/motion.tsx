import { useEffect, useRef, useState, type CSSProperties, type ReactNode } from "react";

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

// 굴러가는 숫자. format 으로 "3,211시간 53분" 같은 표기를 줄 수 있다 (자릿수가 흔들리지 않게 고정폭 숫자).
// 굴러가는 동안 폭이 변하면 문장의 줄바꿈이 매 프레임 다시 계산돼서 글이 아랫줄로 갔다 올라가며 어지럽다.
// 그래서 최종 값을 보이지 않게 깔아 폭을 처음부터 고정하고, 보이는 값은 그 자리 안에서 굴러간다.
// align: 문장 속 숫자는 "end"(뒤 글자에 붙어서 자란다), 카드의 큰 숫자는 기본 "start".
export function Num({
  value,
  format = (n: number) => Math.round(n).toLocaleString(),
  duration,
  align = "start",
}: {
  value: number;
  format?: (n: number) => string;
  duration?: number;
  align?: "start" | "end";
}) {
  const shown = useCountUp(value, duration);
  return (
    <span style={{ display: "inline-grid", fontVariantNumeric: "tabular-nums" }}>
      <span aria-hidden style={{ gridArea: "1 / 1", visibility: "hidden" }}>{format(value)}</span>
      <span style={{ gridArea: "1 / 1", textAlign: align === "end" ? "right" : "left" }}>{format(shown)}</span>
    </span>
  );
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

// 화면에 처음 보이는 순간 true 가 된다 (한 번만). 화면 밖에서 이미 끝나 버리는 애니메이션을 막고, 보이는 순간부터 시작하게 한다.
// 움직임 줄이기 설정이거나 IntersectionObserver 가 없으면 처음부터 true.
export function useInView<T extends Element = HTMLDivElement>(margin = "0px 0px -8% 0px") {
  const ref = useRef<T>(null);
  const [seen, setSeen] = useState(() => prefersReducedMotion() || typeof IntersectionObserver === "undefined");
  useEffect(() => {
    if (seen) return;
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setSeen(true);
          io.disconnect();
        }
      },
      { rootMargin: margin }
    );
    io.observe(el);
    return () => io.disconnect();
  }, [seen, margin]);
  return [ref, seen] as const;
}

// 화면에 보일 때 안쪽을 그린다: 차트가 그 순간부터 자기 애니메이션(펼쳐지기)을 시작한다. 그리기 전에도 자리(minHeight)는 잡아 둬서 레이아웃이 밀리지 않는다.
export function Reveal({ children, minHeight, className, style }: { children: ReactNode; minHeight?: number; className?: string; style?: CSSProperties }) {
  const [ref, seen] = useInView<HTMLDivElement>();
  return (
    <div ref={ref} className={className} style={{ minHeight: seen ? undefined : minHeight, ...style }}>
      {seen && <div className="aym-tab">{children}</div>}
    </div>
  );
}
