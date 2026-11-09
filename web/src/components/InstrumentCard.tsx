import * as Collapsible from "@radix-ui/react-collapsible";
import { CheckCircle2, ChevronDown, CircleAlert, ClipboardCheck, Route } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState } from "react";
import type { Card } from "../types";
import { CardBadges } from "./Badge";

function IdTag({ id }: { id: string }) {
  return <span className="id-tag">{id}</span>;
}

function makeModel(card: Card) {
  return [card.manufacturer, card.model].filter(Boolean).join(" ");
}

function Chips({ items, kind }: { items: string[]; kind: "installed" | "confirm" }) {
  if (!items.length) return null;
  return (
    <div className="chip-group">
      <span className="label">{kind === "installed" ? "Installed" : "Confirm with contact"}</span>
      <ul className="chips">
        {items.map((item) => (
          <li key={item} className={`chip chip--${kind}`}>
            {kind === "installed" ? (
              <CheckCircle2 size={16} aria-hidden="true" />
            ) : (
              <ClipboardCheck size={16} aria-hidden="true" />
            )}
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Details({ card }: { card: Card }) {
  const [open, setOpen] = useState(false);
  const hasAny =
    card.installed.length || card.to_confirm.length || card.workflow.length || card.cautions.length || card.dead_end;
  if (!hasAny && !card.capabilities_note && !card.demo_instrument) return null;
  return (
    <Collapsible.Root open={open} onOpenChange={setOpen} className="details">
      <Collapsible.Trigger className="details__trigger">
        <ChevronDown size={18} aria-hidden="true" className={open ? "rot" : ""} />
        Details
        {card.to_confirm.length > 0 && !open && (
          <span className="details__hint">{card.to_confirm.length} to confirm</span>
        )}
      </Collapsible.Trigger>
      <AnimatePresence initial={false}>
        {open && (
          <Collapsible.Content forceMount asChild>
            <motion.div
              className="details__body"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.2, ease: "easeOut" }}
            >
              <div className="details__inner">
                {card.dead_end && (
                  <p className="dead-end">
                    <CircleAlert size={18} aria-hidden="true" />
                    {card.dead_end}
                  </p>
                )}
                <Chips items={card.installed} kind="installed" />
                <Chips items={card.to_confirm} kind="confirm" />
                {card.workflow.length > 0 && (
                  <div className="workflow">
                    <span className="label">
                      <Route size={14} aria-hidden="true" /> Workflow
                    </span>
                    <ul>
                      {card.workflow.map((line) => (
                        <li key={line}>{line}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {card.cautions.length > 0 && (
                  <ul className="cautions">
                    {card.cautions.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                )}
                <p className="details__meta">
                  {[card.capabilities_note, card.demo_instrument ? "Demo instrument" : ""].filter(Boolean).join(" · ")}
                </p>
              </div>
            </motion.div>
          </Collapsible.Content>
        )}
      </AnimatePresence>
    </Collapsible.Root>
  );
}

/** A primary recommendation, styled like an equipment asset tag. */
export function InstrumentCard({ card }: { card: Card }) {
  const reasonTone = card.dead_end ? "dead" : card.fit ?? "neutral";
  return (
    <article className="card" aria-label={`${card.name} (${card.id})`}>
      <header className="card__strip">
        <IdTag id={card.id} />
        <CardBadges card={card} />
      </header>
      <div className="card__body">
        <h4 className="card__title">{card.name}</h4>
        <p className="mono card__model">{makeModel(card)}</p>
        {card.fit_reason && <p className={`fit-reason fit-reason--${reasonTone}`}>{card.fit_reason}</p>}
        {card.technique && (
          <p className="card__why">
            <strong>{card.technique}.</strong> {card.why}
          </p>
        )}
        {!card.fit && card.to_confirm.length > 0 && (
          <p className="confirm-line">
            <ClipboardCheck size={18} aria-hidden="true" />
            <span>
              <strong>Confirm with the contact:</strong> {card.to_confirm.join("; ")}
            </span>
          </p>
        )}
        <dl className="facts">
          <div>
            <dt>Location</dt>
            <dd>{card.location}</dd>
          </div>
          <div>
            <dt>Contact</dt>
            <dd>{card.contact}</dd>
          </div>
          <div>
            <dt>Destructive</dt>
            <dd>{card.destructive ? capitalize(card.destructive) : "Not stated"}</dd>
          </div>
        </dl>
        <Details card={card} />
      </div>
    </article>
  );
}

/** A complementary instrument: compact, one line on why it only helps. */
export function CompactCard({ card }: { card: Card }) {
  return (
    <article className="card card--compact" aria-label={`${card.name} (${card.id})`}>
      <header className="card__strip">
        <IdTag id={card.id} />
        <CardBadges card={card} compact />
      </header>
      <div className="card__body">
        <h4 className="card__title card__title--sm">{card.name}</h4>
        <p className="mono card__model">{makeModel(card)}</p>
        <p className="card__purpose">{card.dead_end || card.why || card.fit_reason}</p>
        <p className="card__where">
          {card.location} · {card.contact}
        </p>
      </div>
    </article>
  );
}

function capitalize(text: string) {
  return text.charAt(0).toUpperCase() + text.slice(1);
}
