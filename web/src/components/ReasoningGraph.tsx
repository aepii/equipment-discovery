import dagre from "@dagrejs/dagre";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  Position,
  ReactFlow,
  ReactFlowProvider,
  useNodesInitialized,
  useNodesState,
  useReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { RotateCcw } from "lucide-react";
import { useReducedMotion } from "motion/react";
import { useEffect, useMemo, useState } from "react";
import type { GraphData, GraphNode } from "../types";

const STEP_MS = 450; // between reasoning ranks
const EDGE_ANIMATION_MS = 1400;

// A mapped type (not the interface itself), so it fits React Flow's Record<string, unknown> constraint.
type StepData = Pick<GraphNode, keyof GraphNode> & { shown: boolean };
type StepNode = Node<StepData, "step">;
type Positions = Record<string, { x: number; y: number }>;

/** One box in the graph, in the answer's own colours (fit level, not available, ...). */
function StepBox({ data }: NodeProps<StepNode>) {
  const [first, ...rest] = data.label.split("\n");
  return (
    <div
      className={`gnode gnode--${data.kind}${data.dashed ? " gnode--dashed" : ""}${data.shown ? " is-shown" : ""}`}
      style={{ background: data.fill, borderColor: data.border }}
    >
      <Handle type="target" position={Position.Left} className="gnode__handle" />
      <strong>{first}</strong>
      {rest.map((line, i) => (
        <span key={i}>{line}</span>
      ))}
      <Handle type="source" position={Position.Right} className="gnode__handle" />
    </div>
  );
}

const nodeTypes = { step: StepBox };

/** Each node's rank: steps along the reasoning path from "Your question". */
function ranks(graph: GraphData): Record<string, number> {
  const rank: Record<string, number> = { q: 0 };
  const queue = ["q"];
  while (queue.length) {
    const id = queue.shift()!;
    for (const edge of graph.edges) {
      if (edge.source === id && rank[edge.target] === undefined) {
        rank[edge.target] = rank[id] + 1;
        queue.push(edge.target);
      }
    }
  }
  // Steps that must come first point *into* a technique; they appear together with it.
  for (const edge of graph.edges) {
    if (rank[edge.source] === undefined && rank[edge.target] !== undefined) rank[edge.source] = rank[edge.target];
  }
  return rank;
}

/** Left-to-right positions from dagre, using each box's measured size. */
function layout(graph: GraphData, sizes: Record<string, { width: number; height: number }>): Positions {
  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: 18, ranksep: 64, marginx: 8, marginy: 8 });
  g.setDefaultEdgeLabel(() => ({}));
  for (const node of graph.nodes) g.setNode(node.id, sizes[node.id]);
  for (const edge of graph.edges) g.setEdge(edge.source, edge.target);
  dagre.layout(g);
  return Object.fromEntries(
    graph.nodes.map((node) => {
      const { x, y, width, height } = g.node(node.id);
      return [node.id, { x: x - width / 2, y: y - height / 2 }];
    }),
  );
}

const DASH: Record<string, string | undefined> = { dashed: "6 4", dotted: "2 4", solid: undefined };

function Flow({ graph }: { graph: GraphData }) {
  const reduced = useReducedMotion();
  const { fitView } = useReactFlow();
  const measured = useNodesInitialized();
  const rank = useMemo(() => ranks(graph), [graph]);
  const maxRank = Math.max(0, ...Object.values(rank));
  const [positions, setPositions] = useState<Positions | null>(null);
  // React Flow owns the node state, so it keeps each box's measured size (and any dragging).
  const [nodes, setNodes, onNodesChange] = useNodesState<StepNode>(
    graph.nodes.map((node) => ({
      id: node.id,
      type: "step",
      position: { x: 0, y: 0 },
      data: { ...node, shown: false },
      selectable: false,
    })),
  );
  const [step, setStep] = useState(-1); // ranks up to this one are shown
  const [run, setRun] = useState(0);
  const [settled, setSettled] = useState(false);

  // First render the boxes invisibly to measure them, then lay them out.
  useEffect(() => {
    if (!measured || positions) return;
    const sizes = Object.fromEntries(
      graph.nodes.map((n) => {
        const m = nodes.find((node) => node.id === n.id)?.measured;
        return [n.id, { width: m?.width ?? 180, height: m?.height ?? 48 }];
      }),
    );
    setPositions(layout(graph, sizes));
  }, [measured, positions, graph, nodes]);

  useEffect(() => {
    if (positions) setNodes((all) => all.map((n) => ({ ...n, position: positions[n.id] ?? n.position })));
  }, [positions, setNodes]);

  // Once laid out: fit the view, then reveal rank by rank (all at once with reduced motion).
  useEffect(() => {
    if (!positions) return;
    const frame = requestAnimationFrame(() => void fitView({ padding: 0.06 }));
    setSettled(false);
    if (reduced) {
      setStep(maxRank);
      setSettled(true);
      return () => cancelAnimationFrame(frame);
    }
    setStep(-1);
    const timers = Array.from({ length: maxRank + 1 }, (_, i) => window.setTimeout(() => setStep(i), 150 + i * STEP_MS));
    timers.push(window.setTimeout(() => setSettled(true), 150 + maxRank * STEP_MS + EDGE_ANIMATION_MS));
    return () => {
      cancelAnimationFrame(frame);
      timers.forEach(window.clearTimeout);
    };
  }, [positions, reduced, maxRank, run, fitView]);

  const shownAt = (id: string) => positions !== null && (rank[id] ?? maxRank) <= step;

  useEffect(() => {
    setNodes((all) =>
      all.map((n) => ({ ...n, data: { ...n.data, shown: positions !== null && (rank[n.id] ?? maxRank) <= step } })),
    );
  }, [step, positions, rank, maxRank, setNodes]);

  const edges: Edge[] = graph.edges.map((edge, i) => {
    const visible = shownAt(edge.source) && shownAt(edge.target);
    return {
      id: `e${i}`,
      source: edge.source,
      target: edge.target,
      label: edge.label,
      hidden: !visible,
      // The newest edges move while the reasoning unfolds, then everything settles.
      animated: !settled && visible && (rank[edge.target] ?? maxRank) === step,
      style: { strokeDasharray: DASH[edge.style], stroke: "#7d8a99", strokeWidth: 1.5 },
      labelStyle: { fill: "#566271", fontSize: 11 },
      labelBgStyle: { fill: "#f8fafc" },
      markerEnd: edge.label === "accessories" ? undefined : { type: MarkerType.ArrowClosed, color: "#7d8a99" },
    };
  });

  return (
    <>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        nodeTypes={nodeTypes}
        minZoom={0.2}
        maxZoom={2.5}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={20} color="#dde3ea" />
        <Controls showInteractive={false} position="bottom-right" />
      </ReactFlow>
      {!reduced && positions && (
        <button type="button" className="button button--secondary graph__replay" onClick={() => setRun((r) => r + 1)}>
          <RotateCcw size={16} aria-hidden="true" />
          Replay
        </button>
      )}
    </>
  );
}

export default function ReasoningGraph({ graph }: { graph: GraphData }) {
  return (
    <div className="graph">
      <ReactFlowProvider>
        <Flow graph={graph} />
      </ReactFlowProvider>
    </div>
  );
}
