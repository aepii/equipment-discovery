import { useQuery } from "@tanstack/react-query";
import { CornerDownRight, RotateCcw, TriangleAlert } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { useState, type ReactNode } from "react";
import { ask, type AskInput } from "../api";
import type { AskResponse, Mode, Stage, Turn } from "../types";
import { AnswerDocument } from "./AnswerDocument";
import { AnswerSkeleton, StageList } from "./Thinking";

export interface AskContext {
  sessionId: string;
  conversationId: string;
  previous: { question: string; standalone_question: string }[];
}

/** One answer for one mode: from the turn if already answered, else asked now (with live stages). */
export function useAnswer(turn: Turn, mode: Mode, ctx: AskContext, onAnswered: (mode: Mode, a: AskResponse) => void) {
  const [stage, setStage] = useState<Stage | null>(null);
  const saved = turn.answers[mode];
  const query = useQuery({
    queryKey: ["answer", turn.id, mode],
    enabled: !saved,
    staleTime: Infinity,
    gcTime: Infinity,
    retry: false,
    refetchOnWindowFocus: false,
    queryFn: async () => {
      setStage(null);
      const input: AskInput = {
        question: turn.question,
        mode,
        conversation: ctx.previous,
        session_id: ctx.sessionId,
        conversation_id: ctx.conversationId,
      };
      const answer = await ask(input, setStage);
      if (!answer.result.error) onAnswered(mode, answer); // errors are not kept, so "Try again" asks anew
      return answer;
    },
  });
  return { answer: saved ?? query.data, stage, error: query.error, retry: () => void query.refetch(), loading: query.isFetching };
}

export function Pending({ stage }: { stage: Stage | null }) {
  return (
    <div className="doc doc--pending">
      <StageList stage={stage} />
      <AnswerSkeleton />
    </div>
  );
}

export function Failure({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="doc doc--error" role="alert">
      <p>
        <TriangleAlert size={20} aria-hidden="true" />
        {message}
      </p>
      <button type="button" className="button button--secondary" onClick={onRetry}>
        <RotateCcw size={18} aria-hidden="true" />
        Try again
      </button>
    </div>
  );
}

export function QuestionBubble({ text }: { text: string }) {
  return (
    <div className="bubble-row">
      <p className="bubble">{text}</p>
    </div>
  );
}

export function RewriteLine({ answer }: { answer?: AskResponse }) {
  if (!answer?.rewritten) return null;
  return (
    <p className="rewrite">
      <CornerDownRight size={16} aria-hidden="true" />
      <span>
        Answering: <em>{answer.standalone_question}</em>
      </span>
    </p>
  );
}

/** The main answer slot: progress, error with retry, or the answer document (cross-faded). */
export function AnswerSlot({ state, render }: {
  state: ReturnType<typeof useAnswer>;
  render: (answer: AskResponse) => ReactNode;
}) {
  const { answer, stage, error, retry, loading } = state;
  const resultError = answer?.result.error;
  let key: string;
  let content: ReactNode;
  if (answer && !loading && !resultError) {
    key = "answer";
    content = render(answer);
  } else if (!loading && (error || resultError)) {
    key = "error";
    content = <Failure message={resultError || (error instanceof Error ? error.message : "Something went wrong.")} onRetry={retry} />;
  } else {
    key = "pending";
    content = <Pending stage={stage} />;
  }
  return (
    <AnimatePresence mode="wait" initial={false}>
      <motion.div key={key} initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: 0.18 }}>
        {content}
      </motion.div>
    </AnimatePresence>
  );
}

export function TurnView({ turn, ctx, onAnswered }: {
  turn: Turn;
  ctx: AskContext;
  onAnswered: (turnId: string, mode: Mode, answer: AskResponse) => void;
}) {
  const main = useAnswer(turn, turn.mode, ctx, (mode, a) => onAnswered(turn.id, mode, a));
  return (
    <section className="turn" aria-label="Question and answer">
      <QuestionBubble text={turn.question} />
      <RewriteLine answer={main.answer} />
      <AnswerSlot state={main} render={(answer) => <AnswerDocument answer={answer} />} />
    </section>
  );
}
