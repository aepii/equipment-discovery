import type { AskResponse, Example, Health, Mode, Stage } from "./types";

export interface AskInput {
  question: string;
  mode: Mode;
  conversation: { question: string; standalone_question: string }[];
  session_id: string;
  conversation_id: string;
}

export class ApiError extends Error {}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(path);
  if (!response.ok) throw new ApiError(`Request failed (${response.status}).`);
  return response.json() as Promise<T>;
}

export const getHealth = () => getJson<Health>("/api/health");
export const getExamples = () => getJson<Example[]>("/api/examples");

async function askPlain(input: AskInput): Promise<AskResponse> {
  let response: Response;
  try {
    response = await fetch("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    });
  } catch {
    throw new ApiError("Couldn't reach the server. Check the connection and try again.");
  }
  if (!response.ok) throw new ApiError(await errorMessage(response));
  return response.json() as Promise<AskResponse>;
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await response.json();
    if (typeof body.detail === "string") return body.detail;
  } catch {
    /* not JSON */
  }
  return `The server answered with an error (${response.status}). Please try again.`;
}

/** Thrown for an error the server reported while answering (no point retrying another way). */
class AnsweredError extends ApiError {}

/**
 * Ask with live progress (server-sent events). Each "stage" event arrives when that step really
 * happens. Falls back to the plain endpoint if streaming isn't possible.
 */
export async function ask(input: AskInput, onStage: (stage: Stage) => void): Promise<AskResponse> {
  try {
    return await askStream(input, onStage);
  } catch (error) {
    if (error instanceof AnsweredError) throw error;
    return askPlain(input);
  }
}

async function askStream(input: AskInput, onStage: (stage: Stage) => void): Promise<AskResponse> {
  const response = await fetch("/api/ask/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(input),
  });
  if (response.status === 422) throw new AnsweredError(await errorMessage(response));
  if (!response.ok || !response.body) throw new Error("stream unavailable");

  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value.replace(/\r\n/g, "\n");
    let end: number;
    while ((end = buffer.indexOf("\n\n")) >= 0) {
      const block = buffer.slice(0, end);
      buffer = buffer.slice(end + 2);
      const event = /^event: (.*)$/m.exec(block)?.[1];
      const data = /^data: (.*)$/m.exec(block)?.[1];
      if (!event || data === undefined) continue;
      const parsed = JSON.parse(data);
      if (event === "stage") onStage(parsed.stage as Stage);
      else if (event === "result") return parsed as AskResponse;
      else if (event === "error") throw new AnsweredError(parsed.message);
    }
  }
  throw new Error("stream ended without a result");
}

export async function sendFeedback(body: {
  answer_id: string;
  overall: "good" | "bad";
  comment: string;
  instrument_ratings: Record<string, string>;
}): Promise<void> {
  const response = await fetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new ApiError(await errorMessage(response));
}
