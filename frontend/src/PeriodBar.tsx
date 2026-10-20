import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { BASE_URL } from "./config";
import { MUTED } from "./theme";

// 기간 선택 한 곳으로 통합:
//   [ 2026년 9월 ▾ ]  ← 누르면 빠른 선택 / 연도 / 직접 입력 팝오버
//   [2026년] [1월] [2월] … [12월]  ← Apple 리플레이식 칩 줄 (연도를 고르면 그 해의 월 줄로 바뀐다)
// 고르면 앱 전체의 기간 필터(dateRange)가 바뀐다. 데이터가 없는 달은 흐리게 비활성이다.

export type PeriodRange = { start?: string; end?: string; label: string };
type MonthInfo = { key: string; label: string; scrobbles: number; partial: boolean };

const two = (n: number) => String(n).padStart(2, "0");
const iso = (d: Date) => `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}`;

export const ALL_TIME: PeriodRange = { label: "전체 기간" };

export function monthRange(year: number, month: number): PeriodRange {
  const last = new Date(year, month, 0).getDate();
  return { start: `${year}-${two(month)}-01`, end: `${year}-${two(month)}-${two(last)}`, label: `${year}년 ${month}월` };
}

export function yearRange(year: number): PeriodRange {
  return { start: `${year}-01-01`, end: `${year}-12-31`, label: `${year}년` };
}

function lastDays(n: number): PeriodRange {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - n);
  return { start: iso(start), end: iso(end), label: `최근 ${n}일` };
}

const chip = (active: boolean, disabled = false): CSSProperties => ({
  flexShrink: 0,
  padding: "0.3rem 0.85rem",
  border: "none",
  borderRadius: 999,
  background: active ? "rgba(128,128,128,0.28)" : "transparent",
  color: active ? "CanvasText" : MUTED,
  fontWeight: active ? 800 : 500,
  fontSize: "1rem",
  opacity: disabled ? 0.3 : 1,
  cursor: disabled ? "default" : "pointer",
});

const menuBtn = (active = false): CSSProperties => ({
  padding: "0.4rem 0.5rem",
  border: "none",
  borderRadius: 8,
  background: active ? "rgba(128,128,128,0.28)" : "rgba(128,128,128,0.12)",
  color: "CanvasText",
  fontWeight: active ? 700 : 500,
  cursor: "pointer",
  textAlign: "center",
});

export function PeriodBar({ range, onChange }: { range: PeriodRange; onChange: (r: PeriodRange) => void }) {
  const [months, setMonths] = useState<MonthInfo[]>([]);
  const [open, setOpen] = useState(false);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const boxRef = useRef<HTMLDivElement>(null);
  const stripRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${BASE_URL}/api/ai-prompt/periods?period=month`)
      .then((r) => r.json())
      .then((d) => !cancelled && setMonths((d.periods as MonthInfo[]) ?? []))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  // 팝오버 바깥을 누르거나 ESC 를 누르면 닫는다
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !boxRef.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const byKey = useMemo(() => new Map(months.map((m) => [m.key, m])), [months]);
  const years = useMemo(() => [...new Set(months.map((m) => Number(m.key.slice(0, 4))))].sort((a, b) => a - b), [months]);

  // 지금 필터가 정확히 한 해 / 한 달일 때만 칩이 선택 상태가 된다
  const sameYear = range.start && range.end && range.start.slice(0, 4) === range.end.slice(0, 4);
  const selectedYear = sameYear ? Number(range.start!.slice(0, 4)) : null;
  const isWholeYear = selectedYear !== null && range.start === `${selectedYear}-01-01` && range.end === `${selectedYear}-12-31`;
  const selectedMonth =
    selectedYear !== null && range.start!.slice(0, 7) === range.end!.slice(0, 7) && range.start!.endsWith("-01") ? Number(range.start!.slice(5, 7)) : null;
  const monthStrip = selectedYear !== null && (isWholeYear || selectedMonth !== null) && years.includes(selectedYear);
  const isAll = !range.start && !range.end;

  // 고른 칩이 줄 밖으로 밀려나 있으면(좁은 화면) 보이는 위치로 스크롤한다
  useEffect(() => {
    // scrollIntoView 는 페이지 전체를 가로로 밀 수 있어서, 칩 줄의 scrollLeft 만 직접 조정한다
    const box = stripRef.current;
    const el = box?.querySelector<HTMLElement>('[data-active="true"]');
    if (box && el) box.scrollTo({ left: el.offsetLeft - (box.clientWidth - el.clientWidth) / 2, behavior: "smooth" });
  }, [range.start, range.end, months.length]);

  const pick = (r: PeriodRange) => {
    onChange(r);
    setOpen(false);
  };
  const strip: CSSProperties = { display: "flex", gap: "0.2rem", overflowX: "auto", whiteSpace: "nowrap", flex: 1, minWidth: 0, scrollbarWidth: "none", alignItems: "center" };

  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", margin: "0.3rem 0 0.8rem" }}>
      <div ref={boxRef} style={{ position: "relative", flexShrink: 0 }}>
        <button
          onClick={() => {
            setFrom(range.start ?? "");
            setTo(range.end ?? "");
            setOpen((v) => !v);
          }}
          aria-haspopup="dialog"
          aria-expanded={open}
          style={{ padding: "0.4rem 0.95rem", border: "none", borderRadius: 999, background: "rgba(128,128,128,0.22)", color: "CanvasText", fontWeight: 800, fontSize: "1rem", cursor: "pointer" }}
        >
          {range.label} <span style={{ opacity: 0.7 }}>▾</span>
        </button>

        {open && (
          <div
            role="dialog"
            aria-label="기간 선택"
            style={{
              position: "absolute",
              top: "calc(100% + 8px)",
              left: 0,
              zIndex: 30,
              width: 300,
              padding: "0.9rem",
              borderRadius: 14,
              background: "Canvas",
              color: "CanvasText",
              border: "1px solid rgba(128,128,128,0.35)",
              boxShadow: "0 12px 36px rgba(0,0,0,0.45)",
              textAlign: "left",
            }}
          >
            <div style={{ fontSize: "0.75rem", color: MUTED, marginBottom: 6 }}>빠른 선택</div>
            <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6 }}>
              <button onClick={() => pick(ALL_TIME)} style={menuBtn(isAll)}>
                전체
              </button>
              {[7, 30, 90, 180, 365].map((n) => (
                <button key={n} onClick={() => pick(lastDays(n))} style={menuBtn(range.label === `최근 ${n}일`)}>
                  {n === 365 ? "최근 1년" : `최근 ${n}일`}
                </button>
              ))}
            </div>

            {years.length > 0 && (
              <>
                <div style={{ fontSize: "0.75rem", color: MUTED, margin: "12px 0 6px" }}>연도</div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 6 }}>
                  {years.map((y) => (
                    <button key={y} onClick={() => pick(yearRange(y))} style={menuBtn(selectedYear === y)}>
                      {y}년
                    </button>
                  ))}
                </div>
              </>
            )}

            <div style={{ fontSize: "0.75rem", color: MUTED, margin: "12px 0 6px" }}>직접 입력</div>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} style={{ flex: 1, minWidth: 0, padding: "0.35rem" }} />
              <span style={{ color: MUTED }}>~</span>
              <input type="date" value={to} onChange={(e) => setTo(e.target.value)} style={{ flex: 1, minWidth: 0, padding: "0.35rem" }} />
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 6, marginTop: 10 }}>
              <button onClick={() => setOpen(false)} style={{ ...menuBtn(), padding: "0.4rem 0.9rem" }}>
                닫기
              </button>
              <button
                disabled={!from && !to}
                onClick={() => pick({ start: from || undefined, end: to || undefined, label: from && to ? `${from} ~ ${to}` : from ? `${from} ~` : `~ ${to}` })}
                style={{ ...menuBtn(true), padding: "0.4rem 0.9rem", fontWeight: 800, opacity: !from && !to ? 0.4 : 1 }}
              >
                적용
              </button>
            </div>
          </div>
        )}
      </div>

      {years.length > 0 && (
        <div ref={stripRef} style={strip} role="tablist" aria-label="기간 칩">
          {monthStrip && selectedYear !== null ? (
            <>
              <button data-active={isWholeYear} onClick={() => onChange(yearRange(selectedYear))} style={chip(isWholeYear)}>
                {selectedYear}년
              </button>
              {Array.from({ length: 12 }, (_, i) => i + 1).map((m) => {
                const info = byKey.get(`${selectedYear}-${two(m)}`);
                return (
                  <button
                    key={m}
                    data-active={selectedMonth === m}
                    disabled={!info}
                    title={info ? `${selectedYear}년 ${m}월 · ${info.scrobbles.toLocaleString()}회${info.partial ? " (일부 기간)" : ""}` : "기록 없음"}
                    onClick={() => onChange(monthRange(selectedYear, m))}
                    style={chip(selectedMonth === m, !info)}
                  >
                    {m}월
                  </button>
                );
              })}
            </>
          ) : (
            <>
              <button data-active={isAll} onClick={() => onChange(ALL_TIME)} style={chip(isAll)}>
                전체
              </button>
              {years.map((y) => (
                <button key={y} onClick={() => onChange(yearRange(y))} style={chip(false)}>
                  {y}년
                </button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
