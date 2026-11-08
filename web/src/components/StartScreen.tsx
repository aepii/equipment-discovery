import type { ReactNode } from "react";
import type { Example } from "../types";

const STEPS = [
  ["Describe your problem", "In plain words. You don't need to know the technique or the instrument."],
  ["We match techniques", "Your question becomes what to measure, then the techniques that measure it."],
  ["Checked against campus equipment", "Only instruments that exist on campus, with location, contact and what to confirm."],
];

export function StartScreen({ composer, examples, onExample }: {
  composer: ReactNode;
  examples: Example[];
  onExample: (question: string) => void;
}) {
  return (
    <div className="start">
      <h1 className="start__title">What do you need to measure?</h1>
      <p className="start__intro">Describe your research problem; we'll find the equipment on campus.</p>
      {composer}
      {examples.length > 0 && (
        <section className="examples" aria-labelledby="examples-title">
          <h2 id="examples-title" className="section-title">Try an example</h2>
          <div className="examples__grid">
            {examples.map((example) => (
              <button key={example.question} type="button" className="example" onClick={() => onExample(example.question)}>
                <span className="mono example__field">{example.field}</span>
                <span className="example__question">{example.question}</span>
              </button>
            ))}
          </div>
        </section>
      )}
      <section className="how" aria-labelledby="how-title">
        <h2 id="how-title" className="section-title">How it works</h2>
        <ol className="how__steps">
          {STEPS.map(([title, text], i) => (
            <li key={title}>
              <span className="how__num" aria-hidden="true">{i + 1}</span>
              <div>
                <strong>{title}</strong>
                <p>{text}</p>
              </div>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
