import { Check } from "lucide-react";
import { useReducedMotion } from "motion/react";
import { useEffect, useState } from "react";
import type { Stage } from "../types";

const STAGES: { key: Stage | "building"; label: string }[] = [
  { key: "reading", label: "Reading your question" },
  { key: "matching", label: "Matching techniques" },
  { key: "checking", label: "Checking campus equipment" },
  { key: "building", label: "Building the answer" },
];
const ORDER: Record<string, number> = { reading: 0, matching: 1, checking: 2, done: 3 };

function Dots() {
  const reduced = useReducedMotion();
  if (reduced) return <span aria-hidden="true">…</span>;
  return (
    <span className="dots" aria-hidden="true">
      <span />
      <span />
      <span />
    </span>
  );
}

export function useElapsed(running: boolean) {
  const [start] = useState(() => Date.now());
  const [now, setNow] = useState(start);
  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(() => setNow(Date.now()), 100);
    return () => window.clearInterval(timer);
  }, [running]);
  return (now - start) / 1000;
}

/** The stages the server has actually reached, with elapsed time. */
export function StageList({ stage }: { stage: Stage | null }) {
  const elapsed = useElapsed(true);
  // "checking" means the model answered and the code checks are running; "building" follows it.
  const current = stage ? ORDER[stage] : 0;
  return (
    <div className="stages" role="status" aria-live="polite">
      <ol>
        {STAGES.map((s, i) => {
          const state = i < current ? "done" : i === current ? "active" : "todo";
          return (
            <li key={s.key} className={`stage stage--${state}`}>
              <span className="stage__icon" aria-hidden="true">
                {state === "done" ? <Check size={16} /> : <span className="stage__ring" />}
              </span>
              <span>{s.label}</span>
              {state === "active" && <Dots />}
            </li>
          );
        })}
      </ol>
      <span className="mono stages__time">{elapsed.toFixed(1)} s</span>
    </div>
  );
}

/** The answer's real shape (summary, plan, one card) while waiting. */
export function AnswerSkeleton() {
  return (
    <div className="skeleton" aria-hidden="true">
      <div className="sk sk--line" style={{ width: "92%" }} />
      <div className="sk sk--line" style={{ width: "78%" }} />
      <div className="sk sk--line" style={{ width: "54%" }} />
      <div className="sk-plan">
        <div className="sk sk--box" />
        <div className="sk sk--box" />
        <div className="sk sk--box" />
      </div>
      <div className="sk sk--card" />
    </div>
  );
}
