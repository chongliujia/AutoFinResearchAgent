from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from autofin.intent import ChatResponder, DeterministicChatResponder, DeterministicIntentParser, IntentParser
from autofin.runtime import ResearchOrchestrator, SkillRegistry, TraceLogger
from autofin.schemas import ResearchTask
from autofin.skills import SecFilingAnalysisSkill
from autofin.skills.base import Skill


JsonDict = Dict[str, Any]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskRecord:
    id: str
    objective: str
    skill_name: str
    inputs: JsonDict
    status: str = "queued"
    messages: List[JsonDict] = field(default_factory=list)
    events: List[JsonDict] = field(default_factory=list)
    result: Optional[JsonDict] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def public_view(self) -> JsonDict:
        return {
            "id": self.id,
            "objective": self.objective,
            "skill_name": self.skill_name,
            "inputs": self.inputs,
            "status": self.status,
            "messages": self.messages,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "event_count": len(self.events),
        }


class TaskStore:
    def __init__(
        self,
        intent_parser: Optional[IntentParser] = None,
        chat_responder: Optional[ChatResponder] = None,
        skills: Optional[Iterable[Skill]] = None,
    ) -> None:
        self._tasks: Dict[str, TaskRecord] = {}
        self._lock = Lock()
        self._registry = SkillRegistry(skills or [SecFilingAnalysisSkill()])
        self._intent_parser = intent_parser or DeterministicIntentParser()
        self._chat_responder = chat_responder or DeterministicChatResponder()

    def list_skills(self) -> List[JsonDict]:
        return [
            {
                "name": skill.name,
                "description": skill.description,
                "permissions": skill.permissions.to_dict(),
            }
            for skill in self._registry.list()
        ]

    def create_task(
        self,
        objective: str,
        skill_name: str,
        inputs: JsonDict,
        messages: Optional[List[JsonDict]] = None,
    ) -> TaskRecord:
        task_id = str(uuid4())
        record = TaskRecord(
            id=task_id,
            objective=objective,
            skill_name=skill_name,
            inputs=inputs,
            messages=messages or [],
        )
        record.events.append(
            self._event(
                "task_created",
                "Task created",
                {"objective": objective, "skill_name": skill_name, "inputs": inputs},
            )
        )
        with self._lock:
            self._tasks[task_id] = record
        return record

    def create_chat_task(self, message: str) -> tuple[Optional[TaskRecord], JsonDict]:
        parsed = self._intent_parser.parse(message)
        user_message = self._message("user", message)

        if parsed.get("intent_type") == "conversation":
            reply, responder_metadata = self._chat_responder.reply(message)
            assistant_message = self._message(
                "assistant",
                reply or parsed.get("reply") or "我在。你可以和我普通对话，也可以让我创建金融研究任务。",
                {"intent_type": "conversation", **responder_metadata},
            )
            return None, {
                "assistant_message": assistant_message,
                "parsed": parsed,
                "conversation": True,
            }

        if not parsed.get("ticker"):
            assistant_message = self._message(
                "assistant",
                "我需要一个股票代码才能开始研究。比如：分析 AAPL 最近的 10-K，重点看风险因素和现金流。",
                {"needs": ["ticker"]},
            )
            return None, {"assistant_message": assistant_message, "parsed": parsed}

        ticker = parsed["ticker"]
        filing_type = parsed["filing_type"]
        objective = parsed["objective"]
        assistant_message = self._message(
            "assistant",
            (
                f"我会创建一个结构化研究任务：使用 sec_filing_analysis 分析 "
                f"{ticker} 的 {filing_type}。执行过程会在 Timeline 和 Evidence 面板里展示。"
            ),
            {"ticker": ticker, "filing_type": filing_type, "skill_name": "sec_filing_analysis"},
        )
        record = self.create_task(
            objective=objective,
            skill_name="sec_filing_analysis",
            inputs={"ticker": ticker, "filing_type": filing_type},
            messages=[user_message, assistant_message],
        )
        return record, {"assistant_message": assistant_message, "parsed": parsed}

    def stream_chat_reply(self, message: str):
        yield from self._chat_responder.stream_reply(message)

    def get_task(self, task_id: str) -> TaskRecord:
        with self._lock:
            try:
                return self._tasks[task_id]
            except KeyError as exc:
                raise KeyError(f"Unknown task: {task_id}") from exc

    def list_tasks(self) -> List[JsonDict]:
        with self._lock:
            records = sorted(
                self._tasks.values(),
                key=lambda task: task.created_at,
                reverse=True,
            )
            return [record.public_view() for record in records]

    def events_since(self, task_id: str, cursor: int) -> List[JsonDict]:
        record = self.get_task(task_id)
        return record.events[cursor:]

    def run_task(self, task_id: str) -> None:
        record = self.get_task(task_id)
        self._set_status(task_id, "running")
        skill = self._registry.get(record.skill_name)
        self._append_event(
            task_id,
            "tool_call_requested",
            f"Tool call requested: {skill.name}",
            {
                "tool": skill.name,
                "inputs": record.inputs,
                "permissions": skill.permissions.to_dict(),
            },
        )
        self._append_event(
            task_id,
            "runtime_started",
            "LangGraph workflow started",
            {"skill_name": record.skill_name},
        )

        try:
            orchestrator = ResearchOrchestrator(
                self._registry,
                trace_logger=TraceLogger(f".autofin/traces/{task_id}.jsonl"),
            )
            result = orchestrator.run(
                ResearchTask(
                    objective=record.objective,
                    skill_name=record.skill_name,
                    inputs=record.inputs,
                )
            )
            with self._lock:
                current = self._tasks[task_id]
                current.result = result
                current.status = "completed"
                current.updated_at = utc_now()
            skill_result = result.get("result", {})
            evidence = skill_result.get("evidence", [])
            self._append_event(
                task_id,
                "tool_call_completed",
                f"Tool call completed: {skill.name}",
                {
                    "tool": skill.name,
                    "trace_id": result.get("trace_id"),
                    "status": skill_result.get("data", {}).get("status"),
                    "evidence_count": len(evidence),
                    "evidence": evidence,
                },
            )
            self._append_event(
                task_id,
                "runtime_completed",
                "Research task completed",
                {"selected_skill": result.get("selected_skill"), "trace_id": result.get("trace_id")},
            )
        except Exception as exc:  # pragma: no cover - defensive API boundary
            with self._lock:
                current = self._tasks[task_id]
                current.error = str(exc)
                current.status = "failed"
                current.updated_at = utc_now()
            self._append_event(task_id, "runtime_failed", "Research task failed", {"error": str(exc)})

    def _set_status(self, task_id: str, status: str) -> None:
        with self._lock:
            record = self._tasks[task_id]
            record.status = status
            record.updated_at = utc_now()

    def _append_event(self, task_id: str, event_type: str, message: str, payload: JsonDict) -> None:
        event = self._event(event_type, message, payload)
        with self._lock:
            record = self._tasks[task_id]
            record.events.append(event)
            record.updated_at = utc_now()

    def _event(self, event_type: str, message: str, payload: JsonDict) -> JsonDict:
        return {
            "event_type": event_type,
            "message": message,
            "payload": payload,
            "timestamp": utc_now(),
        }

    def _message(self, role: str, content: str, metadata: Optional[JsonDict] = None) -> JsonDict:
        return {
            "role": role,
            "content": content,
            "metadata": metadata or {},
            "timestamp": utc_now(),
        }
