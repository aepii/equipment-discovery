export type Mode = "annotated" | "naive" | "structured";
export type Fit = "high" | "medium" | "low";
export type Stage = "reading" | "matching" | "checking" | "done";

export interface Card {
  id: string;
  name: string;
  manufacturer: string;
  model: string;
  location: string;
  contact: string;
  demo_instrument: boolean;
  role: "primary" | "supplementary";
  technique: string;
  property: string;
  why: string;
  fit: Fit | null;
  fit_reason: string;
  destructive_level: "yes" | "no" | "depends" | "aliquot" | null;
  destructive: string;
  dead_end: string;
  installed: string[];
  to_confirm: string[];
  workflow: string[];
  cautions: string[];
  capabilities_note: string;
}

export interface Plan {
  need: string;
  technique: string;
  instrument: string;
  instrument_id: string;
}

export interface NotAvailable {
  technique: string;
  why_useful: string;
}

/** The sanitized answer. Fields after `seconds` are absent when there is an error. */
export interface AnswerResult {
  mode: Mode;
  mode_label: string;
  error: string | null;
  seconds: number | null;
  // Equipment Finder / rules-only answers
  summary?: string;
  clarifying_question?: string | null;
  measurement_needs?: string[];
  objective_met?: boolean;
  plan?: Plan | null;
  primary?: Card[];
  complementary?: Card[];
  not_available?: NotAvailable[];
  removed_count?: number;
  // General AI answers
  text?: string;
  gaps?: string[];
}

export interface GraphNode {
  id: string;
  label: string;
  kind: "question" | "property" | "technique" | "instrument" | "accessories" | "missing" | "other";
  fill: string;
  border: string;
  dashed: boolean;
}

export interface GraphEdge {
  source: string;
  target: string;
  label: string;
  style: "solid" | "dashed" | "dotted";
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface AskResponse {
  answer_id: string;
  question: string;
  standalone_question: string;
  rewritten: boolean;
  source: "live" | "cache" | "saved";
  result: AnswerResult;
  graph_dot: string | null;
  graph?: GraphData | null;
}

export interface Instrument {
  id: string;
  name: string;
  manufacturer: string;
  model: string;
  location: string;
  contact: string;
  demo_instrument: boolean;
  installed: string[];
  techniques: string[];
}

export interface Example {
  field: string;
  question: string;
}

export interface Health {
  provider: string;
  model: string;
  live: boolean;
  footer: string;
}

export interface Turn {
  id: string;
  question: string;
  compare: boolean;
  mode: Mode; // the main answer's mode (Equipment Finder unless changed in Advanced)
  answers: Partial<Record<Mode, AskResponse>>;
}

export interface Conversation {
  id: string;
  title: string;
  createdAt: number;
  turns: Turn[];
}
