import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getExamples, getHealth } from "./api";
import { Composer } from "./components/Composer";
import { Footer, Header } from "./components/Header";
import { Sidebar } from "./components/Sidebar";
import { StartScreen } from "./components/StartScreen";
import { TurnView } from "./components/TurnView";
import { load, newId, remove, save, sessionId } from "./storage";
import type { AskResponse, Conversation, Mode, Turn } from "./types";

const SESSION = sessionId();
const HISTORY_KEY = "ef.conversations";
const MODE_KEY = "ef.mode";
const MAX_CONVERSATIONS = 30;

function newConversation(): Conversation {
  return { id: newId(), title: "", createdAt: Date.now(), turns: [] };
}

/** Saved conversations keep only answered turns (an unanswered one would be asked again on reload). */
function forStorage(conversations: Conversation[]): Conversation[] {
  return conversations
    .map((c) => ({ ...c, turns: c.turns.filter((t) => t.answers[t.mode]) }))
    .filter((c) => c.turns.length > 0)
    .slice(0, MAX_CONVERSATIONS);
}

export default function App() {
  const examples = useQuery({ queryKey: ["examples"], queryFn: getExamples, staleTime: Infinity });
  const health = useQuery({ queryKey: ["health"], queryFn: getHealth, staleTime: Infinity });
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    const stored = load<Conversation[]>(HISTORY_KEY, []);
    return [newConversation(), ...(Array.isArray(stored) ? stored : [])];
  });
  const [activeId, setActiveId] = useState(() => conversations[0].id);
  const [draft, setDraft] = useState("");
  const [compare, setCompare] = useState(false);
  const [mode, setMode] = useState<Mode>(() =>
    load<Mode>(MODE_KEY, "annotated") === "structured" ? "structured" : "annotated",
  );
  const threadEnd = useRef<HTMLDivElement>(null);

  const active = conversations.find((c) => c.id === activeId) ?? conversations[0];
  const turns = active.turns;

  useEffect(() => save(HISTORY_KEY, forStorage(conversations)), [conversations]);
  useEffect(() => save(MODE_KEY, mode), [mode]);

  const submit = (text: string) => {
    const question = text.trim();
    if (!question) return;
    const turn: Turn = { id: newId(), question, compare, mode, answers: {} };
    setConversations((all) =>
      all.map((c) => (c.id === active.id ? { ...c, title: c.title || question, turns: [...c.turns, turn] } : c)),
    );
    setDraft("");
  };

  const onAnswered = useCallback((turnId: string, answerMode: Mode, answer: AskResponse) => {
    setConversations((all) =>
      all.map((c) => ({
        ...c,
        turns: c.turns.map((t) => (t.id === turnId ? { ...t, answers: { ...t.answers, [answerMode]: answer } } : t)),
      })),
    );
  }, []);

  const startNew = () => {
    if (active.turns.length === 0) return;
    const fresh = newConversation();
    setConversations((all) => [fresh, ...all.filter((c) => c.turns.length > 0)]);
    setActiveId(fresh.id);
    setDraft("");
  };

  const clearHistory = () => {
    if (!window.confirm("Clear all conversations saved in this browser?")) return;
    const fresh = newConversation();
    remove(HISTORY_KEY);
    setConversations([fresh]);
    setActiveId(fresh.id);
  };

  useEffect(() => {
    threadEnd.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [turns.length, activeId]);

  // For follow-ups: the earlier standalone questions of this conversation, per turn.
  const contexts = useMemo(
    () =>
      turns.map((_, i) => ({
        sessionId: SESSION,
        conversationId: active.id,
        previous: turns.slice(0, i).map((t) => ({
          question: t.question,
          standalone_question: t.answers[t.mode]?.standalone_question ?? t.question,
        })),
      })),
    [turns, active.id],
  );

  const composer = (
    <Composer
      value={draft}
      onChange={setDraft}
      onSubmit={() => submit(draft)}
      compare={compare}
      onCompareChange={setCompare}
      busy={false}
      label={turns.length ? "Ask a follow-up" : "Your research question"}
      placeholder={
        turns.length ? "e.g. What about for a hydrogel?" : "e.g. How stiff is my porous scaffold in compression?"
      }
      autoFocus
    />
  );

  return (
    <div className="app">
      <a href="#main" className="skip">
        Skip to content
      </a>
      <Header />
      <div className="layout layout--sidebar">
        <Sidebar
          conversations={conversations}
          activeId={active.id}
          onSelect={setActiveId}
          onNew={startNew}
          onClear={clearHistory}
          mode={mode}
          onModeChange={setMode}
        />
        <main className="main" id="main">
          {turns.length === 0 ? (
            <StartScreen composer={composer} examples={examples.data ?? []} onExample={submit} />
          ) : (
            <>
              <div className={`thread${turns.some((t) => t.compare) ? " thread--wide" : ""}`}>
                {turns.map((turn, i) => (
                  <TurnView key={turn.id} turn={turn} onAnswered={onAnswered} ctx={contexts[i]} />
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
