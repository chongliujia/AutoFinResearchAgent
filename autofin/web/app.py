from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from autofin.config import ModelConfigStore
from autofin.intent import LangChainChatResponder, LangChainIntentParser
from autofin.intent_router import LLMIntentRouter
from autofin.skills import SecFilingAnalysisSkill
from autofin.skills.sec_filing import LangChainEvidenceMemoSynthesizer
from autofin.web.task_store import TaskStore


STATIC_DIR = Path(__file__).parent / "static"


class CreateTaskRequest(BaseModel):
    objective: str = "Analyze SEC filing"
    skill_name: str = "sec_filing_analysis"
    inputs: Dict[str, Any] = Field(default_factory=dict)
    ticker: Optional[str] = None
    filing_type: Optional[str] = "10-K"


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ModelConfigRequest(BaseModel):
    provider: str = "openai-compatible"
    model: str = ""
    base_url: str = ""
    api_key: str = ""
    temperature: float = 0.2


app = FastAPI(title="AutoFinResearchAgent")
model_config_store = ModelConfigStore()
store = TaskStore(
    intent_parser=LangChainIntentParser(model_config_store),
    intent_router=LLMIntentRouter(model_config_store),
    chat_responder=LangChainChatResponder(model_config_store),
    skills=[
        SecFilingAnalysisSkill(
            memo_synthesizer=LangChainEvidenceMemoSynthesizer(model_config_store),
        )
    ],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/skills")
def list_skills():
    return {"skills": store.list_skills()}


@app.get("/api/settings/model")
def get_model_settings():
    return {"model_api": model_config_store.get().public_view()}


@app.post("/api/settings/model")
def update_model_settings(request: ModelConfigRequest):
    config = model_config_store.update(request.model_dump())
    return {"model_api": config.public_view()}


@app.get("/api/tasks")
def list_tasks():
    return {"tasks": store.list_tasks()}


@app.get("/api/sessions")
def list_sessions():
    return {"sessions": store.list_sessions()}


@app.post("/api/sessions")
def create_session():
    return {"session": store.create_session()}


@app.delete("/api/sessions")
def delete_all_sessions():
    return store.delete_all_sessions()


@app.get("/api/sessions/{session_id}")
def get_session(session_id: str):
    try:
        return {"session": store.get_session(session_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/sessions/{session_id}")
def delete_session(session_id: str):
    try:
        return store.delete_session(session_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/tasks")
def create_task(request: CreateTaskRequest, background_tasks: BackgroundTasks):
    inputs = dict(request.inputs)
    if request.ticker:
        inputs["ticker"] = request.ticker
    if request.filing_type:
        inputs.setdefault("filing_type", request.filing_type)

    record = store.create_task(request.objective, request.skill_name, inputs)
    background_tasks.add_task(store.run_task, record.id)
    return record.public_view()


@app.post("/api/chat")
def create_chat_task(request: ChatRequest, background_tasks: BackgroundTasks):
    return {
        "status": "routed",
        "task": None,
        **store.preview_chat(request.message, session_id=request.session_id),
    }


@app.post("/api/research/run")
def run_research_from_chat(request: ChatRequest, background_tasks: BackgroundTasks):
    record, chat_result = store.create_research_task_from_message(request.message, session_id=request.session_id)
    if record is None:
        return {
            "status": chat_result["policy_decision"]["action"],
            "task": None,
            **chat_result,
        }

    background_tasks.add_task(store.run_task, record.id)
    return {
        "status": "task_created",
        "task": record.public_view(),
        **chat_result,
    }


@app.post("/api/chat/stream")
def stream_chat(request: ChatRequest):
    async def stream():
        for event_name, payload in store.stream_chat_events(request.message, session_id=request.session_id):
            yield f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0)
        yield f"event: chat-done\ndata: {json.dumps({'status': 'done'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/tasks/{task_id}")
def get_task(task_id: str):
    try:
        return store.get_task(task_id).public_view()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/tasks/{task_id}/artifacts/{artifact_index}")
def get_task_artifact(task_id: str, artifact_index: int):
    try:
        task = store.get_task(task_id).public_view()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    artifacts = task.get("result", {}).get("result", {}).get("data", {}).get("analysis", {}).get("artifacts", [])
    if artifact_index < 0 or artifact_index >= len(artifacts):
        raise HTTPException(status_code=404, detail="Artifact not found")

    artifact = artifacts[artifact_index]
    path = artifact.get("path")
    if not path:
        raise HTTPException(status_code=404, detail="Artifact has no readable path")

    artifact_path = Path(path)
    if not artifact_path.is_file():
        raise HTTPException(status_code=404, detail="Artifact file not found")

    return {
        "artifact": artifact,
        "content": artifact_path.read_text(encoding="utf-8"),
    }


@app.get("/api/tasks/{task_id}/events")
async def task_events(task_id: str, cursor: int = 0):
    try:
        store.get_task(task_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def stream():
        next_index = cursor
        while True:
            record = store.get_task(task_id)
            events = record.events[next_index:]
            for event in events:
                payload = {"index": next_index, **event}
                yield f"event: task-event\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                next_index += 1

            if record.status in {"completed", "failed"} and next_index >= len(record.events):
                yield (
                    "event: task-closed\n"
                    f"data: {json.dumps({'status': record.status}, ensure_ascii=False)}\n\n"
                )
                break

            await asyncio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream")
