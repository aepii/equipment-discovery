import * as Dialog from "@radix-ui/react-dialog";
import { Maximize2, Minus, Network, Plus, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

/** The knowledge-graph path behind an answer, rendered from DOT in the browser (Graphviz as WebAssembly). */
function Graph({ dot }: { dot: string }) {
  const [svg, setSvg] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [view, setView] = useState({ scale: 1, x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number } | null>(null);
  const viewport = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLDivElement>(null);

  /** Scale the whole diagram into the viewport (never above actual size). */
  const fit = () => {
    const box = viewport.current;
    const content = canvas.current;
    if (!box || !content) return;
    const scale = Math.min(1, box.clientWidth / content.scrollWidth, box.clientHeight / content.scrollHeight);
    setView({ scale, x: (box.clientWidth - content.scrollWidth * scale) / 2, y: 0 });
  };

  useEffect(() => {
    if (svg) fit();
  }, [svg]);

  useEffect(() => {
    let alive = true;
    import("@viz-js/viz")
      .then((viz) => viz.instance())
      .then((viz) => {
        if (alive) setSvg(viz.renderString(dot, { format: "svg", engine: "dot" }));
      })
      .catch(() => {
        if (alive) setFailed(true);
      });
    return () => {
      alive = false;
    };
  }, [dot]);

  const zoom = (factor: number) => setView((v) => ({ ...v, scale: Math.min(4, Math.max(0.3, v.scale * factor)) }));

  if (failed) return <p className="graph__status">The diagram couldn't be drawn in this browser.</p>;
  if (!svg) return <p className="graph__status">Drawing the diagram…</p>;
  return (
    <div className="graph">
      <div className="graph__tools">
        <button type="button" className="icon-button" aria-label="Zoom in" onClick={() => zoom(1.25)}>
          <Plus size={18} aria-hidden="true" />
        </button>
        <button type="button" className="icon-button" aria-label="Zoom out" onClick={() => zoom(0.8)}>
          <Minus size={18} aria-hidden="true" />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="Fit to view"
          onClick={fit}
        >
          <Maximize2 size={18} aria-hidden="true" />
        </button>
      </div>
      <div
        ref={viewport}
        className="graph__viewport"
        onWheel={(e) => zoom(e.deltaY < 0 ? 1.1 : 0.9)}
        onPointerDown={(e) => {
          drag.current = { x: e.clientX - view.x, y: e.clientY - view.y };
          e.currentTarget.setPointerCapture(e.pointerId);
        }}
        onPointerMove={(e) => {
          const start = drag.current;
          if (start) setView((v) => ({ ...v, x: e.clientX - start.x, y: e.clientY - start.y }));
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
      >
        <div
          ref={canvas}
          className="graph__canvas"
          style={{ transform: `translate(${view.x}px, ${view.y}px) scale(${view.scale})` }}
          // Graphviz output of the server's own DOT, built from the dataset and the checked answer.
          dangerouslySetInnerHTML={{ __html: svg }}
        />
      </div>
    </div>
  );
}

export function ReasoningButton({ dot }: { dot: string }) {
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
                What you asked about, the techniques that measure it, the instruments and contacts that perform them,
                steps that must come first, and what isn't on campus. Dashed boxes: complementary only or not
                available. Drag to move, scroll to zoom.
              </Dialog.Description>
            </div>
            <Dialog.Close className="icon-button" aria-label="Close">
              <X size={20} aria-hidden="true" />
            </Dialog.Close>
          </header>
          <Graph dot={dot} />
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
