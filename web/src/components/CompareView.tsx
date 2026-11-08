import * as Tabs from "@radix-ui/react-tabs";
import { Check, CircleMinus } from "lucide-react";
import Markdown from "react-markdown";
import type { AskResponse } from "../types";
import { useMediaQuery } from "../useMediaQuery";
import { FinderBody, sourceText } from "./AnswerDocument";
import { Badge } from "./Badge";
import { ReasoningButton } from "./Reasoning";
import { AnswerSlot, type AnswerState } from "./TurnView";

const ADDS = [
  "Only equipment that exists on campus, each with its location and contact.",
  "Separates what's installed from the accessories to confirm with the contact.",
  "Says plainly when the right technique isn't available on campus.",
];

function GeneralColumn({ state }: { state: AnswerState }) {
  return (
    <section className="col col--general" aria-label="General AI answer">
      <header className="col__head">
        <span className="col__title">General AI</span>
        <span className="pill">no guidance</span>
      </header>
      <div className="col__body">
        <AnswerSlot
          state={state}
          render={(answer: AskResponse) => (
            <>
              <div className="markdown">
                <Markdown skipHtml>{answer.result.text ?? ""}</Markdown>
              </div>
              {(answer.result.gaps ?? []).length > 0 && (
                <footer className="gaps">
                  <span className="label">What this answer doesn't state</span>
                  <ul>
                    {(answer.result.gaps ?? []).map((gap) => (
                      <li key={gap}>
                        <CircleMinus size={16} aria-hidden="true" />
                        {gap}
                      </li>
                    ))}
                  </ul>
                </footer>
              )}
            </>
          )}
        />
      </div>
    </section>
  );
}

function FinderColumn({ state }: { state: AnswerState }) {
  return (
    <section className="col col--finder" aria-label="Equipment Finder answer">
      <header className="col__head">
        <span className="col__title">Equipment Finder</span>
        <Badge tone="gold">checked against campus equipment</Badge>
        {state.answer && <span className="mono doc__time col__time">{sourceText(state.answer)}</span>}
      </header>
      <div className="col__body">
        <AnswerSlot
          state={state}
          render={(answer) => (
            <FinderBody
              answer={answer}
              actions={answer.graph ? <ReasoningButton graph={answer.graph} /> : undefined}
            />
          )}
        />
      </div>
    </section>
  );
}

export function CompareView({ finder, general }: { finder: AnswerState; general: AnswerState }) {
  const narrow = useMediaQuery("(max-width: 900px)");
  return (
    <div className="compare">
      {narrow ? (
        <Tabs.Root defaultValue="finder">
          <Tabs.List className="tabs" aria-label="Answers">
            <Tabs.Trigger value="finder" className="tab">
              Equipment Finder
            </Tabs.Trigger>
            <Tabs.Trigger value="general" className="tab">
              General AI
            </Tabs.Trigger>
          </Tabs.List>
          <Tabs.Content value="finder">
            <FinderColumn state={finder} />
          </Tabs.Content>
          <Tabs.Content value="general">
            <GeneralColumn state={general} />
          </Tabs.Content>
        </Tabs.Root>
      ) : (
        <div className="compare__cols">
          <GeneralColumn state={general} />
          <FinderColumn state={finder} />
        </div>
      )}
      <section className="adds" aria-labelledby="adds-title">
        <h3 id="adds-title" className="section-title">
          What Equipment Finder adds
        </h3>
        <ul>
          {ADDS.map((item) => (
            <li key={item}>
              <Check size={18} aria-hidden="true" />
              {item}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
