import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useRef, useState } from "react";
import { getExamples, getHealth } from "./api";
import { Composer } from "./components/Composer";
import { Footer, Header } from "./components/Header";
import { StartScreen } from "./components/StartScreen";
import { TurnView } from "./components/TurnView";
import { newId, sessionId } from "./storage";
import type { AskResponse, Conversation, Mode, Turn } from "./types";

const SESSION = sessionId();

function newConversation(): Conversation {
  return { id: newId(), title: "", createdAt: Date.now(), turns: [] };
}

export default function App() {
  const examples = useQuery({ queryKey: ["examples"], queryFn: getExamples, staleTime: Infinity });
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth, staleTime: Infinity });
  const [conversation, setConversation] = useState<Conversation>(newConversation);
  const [draft, setDraft] = useState("");
  const [compare, setCompare] = useState(false);
  const mode: Mode = "annotated";
  const threadEnd = useRef<HTMLDivElement>(null);

  const submit = useCallback(
    (text: string) => {
      const question = text.trim();
      if (!question) return;
      const turn: Turn = { id: newId(), question, compare, mode, answers: {} };
      setConversation((c) => ({ ...c, title: c.title || question, turns: [...c.turns, turn] }));
      setDraft("");
    },
    [compare, mode],
  );

  const onAnswered = useCallback((turnId: string, answerMode: Mode, answer: AskResponse) => {
    setConversation((c) => ({
      ...c,
      turns: c.turns.map((t) => (t.id === turnId ? { ...t, answers: { ...t.answers, [answerMode]: answer } } : t)),
    }));
  }, []);

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [conversation.turns.length]);

  const turns = conversation.turns;
  const composer = (
    <Composer
      value={draft}
      onChange={setDraft}
      onSubmit={() => submit(draft)}
      compare={compare}
      onCompareChange={setCompare}
      busy={false}
      label={turns.length ? "Ask a follow-up" : "Your research question"}
      placeholder={turns.length ? "e.g. What about for a hydrogel?" : "e.g. How stiff is my porous scaffold in compression?"}
      autoFocus
    />
  );

  return (
    <div className="app">
      <Header />
      <div className="layout">
        <main className="main" id="main">
          {turns.length === 0 ? (
            <StartScreen composer={composer} examples={examples.data ?? []} onExample={submit} />
          ) : (
            <>
              <div className={`thread${turns.some((t) => t.compare) ? " thread--wide" : ""}`}>
                {turns.map((turn, i) => (
                  <TurnView
                    key={turn.id}
                    turn={turn}
                    onAnswered={onAnswered}
                    ctx={{
                      sessionId: SESSION,
                      conversationId: conversation.id,
                      previous: turns.slice(0, i).map((t) => {
                        const a = t.answers[t.mode];
                        return { question: t.question, standalone_question: a?.standalone_question ?? t.question };
                      }),
                    }}
                  />
                ))}
                <div ref={threadEnd} />
              </div>
              <div className="composer-dock">{composer}</div>
            </>
          )}
          <Footer note={health.data?.footer ?? "Demo data: contact names are fictional."} />
        </main>
      </div>
    </div>
  );
}
