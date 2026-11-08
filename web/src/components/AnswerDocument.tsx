import { CircleSlash, Info, MessageCircleQuestion, ShieldAlert } from "lucide-react";
import { motion } from "motion/react";
import type { ReactNode } from "react";
import type { AskResponse } from "../types";
import { Feedback } from "./Feedback";
import { CompactCard, InstrumentCard } from "./InstrumentCard";
import { MeasurementPlan } from "./MeasurementPlan";

const reveal = {
  hidden: { opacity: 0, y: 8 },
  shown: { opacity: 1, y: 0, transition: { duration: 0.24, ease: "easeOut" } },
} as const;

export function Reveal({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <motion.div className={className} variants={reveal}>
      {children}
    </motion.div>
  );
}

export function sourceText(answer: AskResponse): string {
  if (answer.source === "saved") return "saved answer";
  if (answer.source === "cache") return "answered earlier";
  return answer.result.seconds != null ? `${answer.result.seconds.toFixed(1)} s` : "";
}

/** The body of an Equipment Finder answer, as a structured report. */
export function FinderBody({ answer, actions }: { answer: AskResponse; actions?: ReactNode }) {
  const r = answer.result;
  const primary = r.primary ?? [];
  const complementary = r.complementary ?? [];
  const notAvailable = r.not_available ?? [];
  const noInstrument = !r.objective_met && !r.clarifying_question;
  return (
    <motion.div
      className="doc__content"
      initial="hidden"
      animate="shown"
      variants={{ shown: { transition: { staggerChildren: 0.05 } } }}
    >
      {r.clarifying_question && (
        <Reveal className="notice notice--info">
          <MessageCircleQuestion size={20} aria-hidden="true" />
          <div>
            <strong>A little more detail would help.</strong>
            <p>{r.clarifying_question}</p>
          </div>
        </Reveal>
      )}
      {r.summary && (
        <Reveal>
          <p className="doc__summary">{r.summary}</p>
        </Reveal>
      )}
      {noInstrument && (
        <Reveal className="notice notice--warn">
          <CircleSlash size={20} aria-hidden="true" />
          <div>
            <strong>No instrument on campus can perform this measurement.</strong>
            {notAvailable.length > 0 && (
              <p>Not available on campus: {notAvailable.map((n) => n.technique).join(", ")}.</p>
            )}
          </div>
        </Reveal>
      )}
      {r.plan && (
        <Reveal>
          <MeasurementPlan plan={r.plan} />
        </Reveal>
      )}
      {primary.length > 0 && (
        <Reveal>
          <section aria-label="Can perform this measurement">
            <h3 className="section-title">Can perform this measurement</h3>
            <div className="cards">
              {primary.map((card) => (
                <InstrumentCard key={card.id} card={card} />
              ))}
            </div>
          </section>
        </Reveal>
      )}
      {complementary.length > 0 && (
        <Reveal>
          <section aria-label="Complementary only">
            <h3 className="section-title">Complementary only</h3>
            <p className="section-note">
              These help with context or sample preparation, but can't perform the main measurement.
            </p>
            <div className="cards cards--grid">
              {complementary.map((card) => (
                <CompactCard key={card.id} card={card} />
              ))}
            </div>
          </section>
        </Reveal>
      )}
      {notAvailable.length > 0 && (
        <Reveal className="unavailable">
          <h3 className="section-title">
            <ShieldAlert size={18} aria-hidden="true" /> Not available on campus
          </h3>
          <ul>
            {notAvailable.map((n) => (
              <li key={n.technique}>
                <strong>{n.technique}</strong>
                {n.why_useful && <> — {n.why_useful}</>}
              </li>
            ))}
          </ul>
        </Reveal>
      )}
      {(r.removed_count ?? 0) > 0 && (
        <Reveal className="notice notice--muted">
          <Info size={18} aria-hidden="true" />
          <p>
            {r.removed_count === 1 ? "One suggestion was" : `${r.removed_count} suggestions were`} removed because
            it named equipment that isn't on campus.
          </p>
        </Reveal>
      )}
      <Reveal className="doc__actions">
        {actions}
        <Feedback answerId={answer.answer_id} cards={[...primary, ...complementary]} />
      </Reveal>
    </motion.div>
  );
}

/** A complete Equipment Finder answer document. */
export function AnswerDocument({ answer, actions }: { answer: AskResponse; actions?: ReactNode }) {
  return (
    <article className="doc" aria-label="Equipment Finder answer">
      <header className="doc__head">
        <span className="label label--strong">{answer.result.mode_label}</span>
        <span className="mono doc__time">{sourceText(answer)}</span>
      </header>
      <FinderBody answer={answer} actions={actions} />
    </article>
  );
}
