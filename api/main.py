"""Web API for the presentation interface. Run with: uvicorn api.main:app

In production it also serves the built frontend (web/dist) at "/".
"""

import json
import queue
import threading
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import llm
from api import presentation, service

DIST = Path(__file__).resolve().parent.parent / "web" / "dist"
MAX_QUESTION = 2000

app = FastAPI(title="Equipment Finder API", docs_url="/api/docs", openapi_url="/api/openapi.json")


class Turn(BaseModel):
    question: str = ""
    standalone_question: str = ""


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=MAX_QUESTION)
    mode: Literal["annotated", "naive", "structured"] = presentation.DEFAULT_MODE
    conversation: list[Turn] = Field(default_factory=list, max_length=50)
    session_id: str = Field(default="", max_length=64)
    conversation_id: str = Field(default="", max_length=64)


class FeedbackRequest(BaseModel):
    answer_id: str = Field(max_length=64)
    overall: Literal["good", "bad", ""] = ""
    comment: str = Field(default="", max_length=4000)
    instrument_ratings: dict[str, Literal["Good", "Partly", "Wrong"]] = Field(default_factory=dict)


@app.get("/api/health")
def health() -> dict:
    return {"provider": llm.provider(), "model": llm.model_name(), "live": service.live_available(),
            "footer": presentation.FICTIONAL_CONTACTS}


@app.get("/api/examples")
def examples() -> list[dict]:
    return presentation.EXAMPLES


@app.get("/api/equipment")
def equipment() -> list[dict]:
    return presentation.equipment()


def _ask(req: AskRequest, on_stage=lambda stage: None) -> dict:
    question = req.question.strip()
    if not question:
        raise HTTPException(422, "Please enter a question.")
    return service.ask(question, req.mode, req.session_id or "anonymous", req.conversation_id,
                       turn=len(req.conversation) + 1, on_stage=on_stage)


@app.post("/api/ask")
def ask(req: AskRequest) -> dict:
    return _ask(req)


def _sse(event: str, data) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/api/ask/stream")
def ask_stream(req: AskRequest) -> StreamingResponse:
    """Server-sent events: a "stage" event when each step actually happens, then "result" (the same
    payload as /api/ask) or "error"."""
    events: queue.Queue = queue.Queue()

    def work() -> None:
        try:
            events.put(("result", _ask(req, on_stage=lambda stage: events.put(("stage", {"stage": stage})))))
        except HTTPException as exc:
            events.put(("error", {"message": exc.detail}))
        except Exception as exc:  # shown as a message with a retry button, never a crash
            print(f"Stream error: {type(exc).__name__}: {exc}")
            events.put(("error", {"message": "Something went wrong while answering. Please try again."}))
        events.put(None)

    def stream():
        threading.Thread(target=work, daemon=True).start()
        while (item := events.get()) is not None:
            yield _sse(*item)

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/feedback")
def feedback(req: FeedbackRequest) -> dict:
    if not service.feedback(req.answer_id, req.overall, req.comment, req.instrument_ratings):
        raise HTTPException(404, "That answer is no longer available for feedback.")
    return {"ok": True}


# --- the built frontend ---

if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{path:path}", include_in_schema=False)
def frontend(path: str):
    """Files from web/dist, and index.html for every other path (the app routes in the browser)."""
    if path.startswith("api/"):
        raise HTTPException(404)
    if not DIST.is_dir():
        raise HTTPException(404, "Frontend not built. Run: cd web && npm run build")
    file = (DIST / path).resolve()
    if path and file.is_file() and DIST in file.parents:
        return FileResponse(file)
    return FileResponse(DIST / "index.html")
