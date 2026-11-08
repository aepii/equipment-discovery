import { ArrowRight } from "lucide-react";
import type { Plan } from "../types";

/** You need to measure -> Technique -> Instrument on campus. */
export function MeasurementPlan({ plan }: { plan: Plan }) {
  const steps = [
    { label: "You need to measure", value: plan.need },
    { label: "Technique", value: plan.technique },
    { label: "Instrument on campus", value: plan.instrument, id: plan.instrument_id },
  ].filter((step) => step.value);
  return (
    <section aria-label="Measurement plan">
      <h3 className="section-title">Measurement plan</h3>
      <ol className="plan">
        {steps.map((step, i) => (
          <li key={step.label} className={`plan__step${step.id ? " plan__step--instrument" : ""}`}>
            {i > 0 && <ArrowRight className="plan__arrow" size={20} aria-hidden="true" />}
            <div className="plan__box">
              <span className="label">{step.label}</span>
              <span className="plan__value">
                {step.value}
                {step.id && <span className="id-tag id-tag--inline">{step.id}</span>}
              </span>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
