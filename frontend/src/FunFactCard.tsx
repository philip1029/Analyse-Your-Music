import { useCallback, useEffect, useState } from "react";
import { BASE_URL } from "./config";
import { LINE } from "./RankRow";
import { MUTED } from "./theme";

// Overview 의 "Did you know?" 카드: 서버가 조건을 넘는 후보를 모두 주고, 여기서 랜덤으로 하나를 보여 준다.
// 후보가 많은 종류(제목 단어, 마일스톤)가 다른 종류를 밀어내지 않도록 group(종류)을 먼저 고른 뒤 그 안에서 고른다.

type Fact = { id: string; group: string; icon: string; text: string };

const pick = <T,>(xs: T[]): T => xs[Math.floor(Math.random() * xs.length)];

function nextFact(facts: Fact[], current: Fact | null): Fact | null {
  if (!facts.length) return null;
  const groups = [...new Set(facts.map((f) => f.group))];
  const others = groups.filter((g) => g !== current?.group);
  const group = pick(others.length ? others : groups);          // 방금 본 종류는 가능하면 피한다
  const inGroup = facts.filter((f) => f.group === group && f.id !== current?.id);
  return pick(inGroup.length ? inGroup : facts.filter((f) => f.group === group));
}

export function FunFactCard() {
  const [facts, setFacts] = useState<Fact[]>([]);
  const [fact, setFact] = useState<Fact | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetch(`${BASE_URL}/api/overview/facts`)
      .then((r) => r.json())
      .then((d) => {
        if (cancelled || !Array.isArray(d.facts)) return;
        setFacts(d.facts);
        setFact(nextFact(d.facts, null));
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const another = useCallback(() => setFact((cur) => nextFact(facts, cur)), [facts]);

  if (!fact) return null;
  return (
    <div style={{ margin: "0.2rem 0 1.2rem", padding: "0.8rem 1.1rem", border: LINE, borderLeft: "4px solid #ffcace", borderRadius: 8, textAlign: "left", display: "flex", alignItems: "center", gap: "0.9rem" }}>
      <div key={fact.id} className="aym-rise" style={{ flex: 1, minWidth: 0 }}>
        <div style={{ color: MUTED, fontSize: "0.78rem", fontWeight: 700, letterSpacing: "0.04em", marginBottom: "0.25rem" }}>DID YOU KNOW?</div>
        <div style={{ fontSize: "1.05rem", lineHeight: 1.45 }}>
          <span aria-hidden style={{ marginRight: "0.45rem" }}>{fact.icon}</span>
          {fact.text}
        </div>
      </div>
      {facts.length > 1 && (
        <button type="button" onClick={another} title="다른 사실 보기" aria-label="다른 사실 보기" style={{ flexShrink: 0, border: LINE, background: "transparent", color: "inherit", borderRadius: 999, padding: "0.3rem 0.8rem", cursor: "pointer", fontSize: "0.85rem" }}>
          ↻ 다른 사실
        </button>
      )}
    </div>
  );
}
