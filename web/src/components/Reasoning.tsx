import * as Dialog from "@radix-ui/react-dialog";
import { Network, X } from "lucide-react";
import { lazy, Suspense } from "react";
import type { GraphData } from "../types";

// The graph library is loaded only when someone opens the reasoning view.
const ReasoningGraph = lazy(() => import("./ReasoningGraph"));

const LEGEND = [
  ["legend--question", "Your question"],
  ["legend--property", "What you asked about"],
  ["legend--technique", "Technique"],
  ["legend--high", "Instrument: high fit"],
  ["legend--medium", "Medium fit"],
  ["legend--low", "Low fit / complementary"],
  ["legend--missing", "Not available on campus"],
];

export function ReasoningButton({ graph }: { graph: GraphData }) {
  return (
    <Dialog.Root>
      <Dialog.Trigger className="button button--secondary">
        <Network size={18} aria-hidden="true" />
        Show reasoning
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog__overlay" />
        <Dialog.Content className="dialog">
          <header className="dialog__head">
            <div>
              <Dialog.Title className="dialog__title">How this answer was reached</Dialog.Title>
              <Dialog.Description className="dialog__desc">
                From your question to what needs measuring, the techniques that measure it, and the instruments and
                contacts that perform them, including steps that must come first and what isn't on campus. Dashed:
                complementary only or not available. Drag to move, scroll to zoom.
              </Dialog.Description>
            </div>
            <Dialog.Close className="icon-button" aria-label="Close">
              <X size={20} aria-hidden="true" />
            </Dialog.Close>
          </header>
          <Suspense fallback={<p className="graph__status">Drawing the diagram…</p>}>
            <ReasoningGraph graph={graph} />
          </Suspense>
          <ul className="legend" aria-label="Legend">
            {LEGEND.map(([cls, text]) => (
              <li key={cls}>
                <span className={`legend__swatch ${cls}`} aria-hidden="true" />
                {text}
              </li>
            ))}
          </ul>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
