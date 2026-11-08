import type { ReactNode } from "react";
import type { Card } from "../types";

type Tone = "role" | "high" | "medium" | "low" | "dead" | "neutral" | "gold";

export function Badge({ tone, children, title }: { tone: Tone; children: ReactNode; title?: string }) {
  return (
    <span className={`badge badge--${tone}`} title={title}>
      <span className="badge__dot" aria-hidden="true" />
      {children}
    </span>
  );
}

const FIT_LABEL = { high: "High fit", medium: "Medium fit", low: "Low fit" } as const;
const DESTRUCTIVE: Record<string, [string, Tone]> = {
  yes: ["Destroys sample", "neutral"],
  no: ["Non-destructive", "neutral"],
  depends: ["Depends on sample", "neutral"],
};

/** Up to three badges: role, fit level (or dead end) and destructiveness. */
export function CardBadges({ card, compact = false }: { card: Card; compact?: boolean }) {
  const primary = card.role === "primary";
  return (
    <div className="badges">
      {!compact && <Badge tone="role">{primary ? "Can perform this" : "Complementary only"}</Badge>}
      {card.dead_end ? (
        <Badge tone="dead">Dead end</Badge>
      ) : (
        card.fit && <Badge tone={card.fit}>{FIT_LABEL[card.fit]}</Badge>
      )}
      {!compact && card.destructive_level && DESTRUCTIVE[card.destructive_level] && (
        <Badge tone={DESTRUCTIVE[card.destructive_level][1]}>{DESTRUCTIVE[card.destructive_level][0]}</Badge>
      )}
    </div>
  );
}
