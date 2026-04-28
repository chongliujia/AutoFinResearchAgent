from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Iterable, List, Optional
from uuid import uuid4

from autofin.intent import ChatResponder, DeterministicChatResponder, DeterministicIntentParser, IntentParser
from autofin.intent_router import DeterministicIntentRouter, IntentRouter
from autofin.policy import PolicyEngine, PolicyLogger
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
        intent_router: Optional[IntentRouter] = None,
        policy_engine: Optional[PolicyEngine] = None,
        policy_logger: Optional[PolicyLogger] = None,
        chat_responder: Optional[ChatResponder] = None,
        skills: Optional[Iterable[Skill]] = None,
    ) -> None:
        self._tasks: Dict[str, TaskRecord] = {}
        self._lock = Lock()
        self._registry = SkillRegistry(skills or [SecFilingAnalysisSkill()])
        self._intent_parser = intent_parser or DeterministicIntentParser()
        self._intent_router = intent_router or DeterministicIntentRouter()
        self._policy_engine = policy_engine or PolicyEngine()
        self._policy_logger = policy_logger or PolicyLogger(Path(".autofin/policy/events.jsonl"))
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

    def preview_chat(self, message: str) -> JsonDict:
        routed_intent, policy_decision = self.route_message(message)
        assistant_message = self._message(
            "assistant",
            self._reply_for_policy(routed_intent, policy_decision),
            {"routed_intent": routed_intent, "policy_decision": policy_decision},
        )
        return {
            "routed_intent": routed_intent,
            "policy_decision": policy_decision,
            "assistant_message": assistant_message,
            "action_card": self._action_card(routed_intent, policy_decision),
        }

    def create_research_task_from_message(self, message: str) -> tuple[Optional[TaskRecord], JsonDict]:
        routed_intent, policy_decision = self.route_message(message)
        result = {
            "routed_intent": routed_intent,
            "policy_decision": policy_decision,
            "action_card": self._action_card(routed_intent, policy_decision),
        }
        if policy_decision.get("action") != "show_run_research_card":
            assistant_message = self._message(
                "assistant",
                self._reply_for_policy(routed_intent, policy_decision),
                {"routed_intent": routed_intent, "policy_decision": policy_decision},
            )
            result["assistant_message"] = assistant_message
            return None, result

        ticker = routed_intent["ticker"]
        filing_type = routed_intent.get("filing_type") or "10-K"
        objective = self._objective_from_routed_intent(message, routed_intent)
        assistant_message = self._message(
            "assistant",
            (
                f"已创建研究任务：使用 sec_filing_analysis 分析 "
                f"{ticker} 的 {filing_type}。执行过程会在 Timeline 和 Evidence 面板里展示。"
            ),
            {"ticker": ticker, "filing_type": filing_type, "skill_name": "sec_filing_analysis"},
        )
        record = self.create_task(
            objective=objective,
            skill_name="sec_filing_analysis",
            inputs={"ticker": ticker, "filing_type": filing_type},
            messages=[self._message("user", message), assistant_message],
        )
        policy_decision["created_task_id"] = record.id
        result["policy_decision"] = policy_decision
        result["assistant_message"] = assistant_message
        self._policy_logger.log(
            message,
            routed_intent,
            policy_decision,
            {"user_clicked_run": True, "created_task_id": record.id},
        )
        return record, result

    def route_message(self, message: str) -> tuple[JsonDict, JsonDict]:
        routed_intent = self._intent_router.route(message)
        policy_decision = self._policy_engine.decide(routed_intent)
        self._policy_logger.log(message, routed_intent, policy_decision)
        return routed_intent, policy_decision

    def stream_chat_events(self, message: str):
        routed_intent, policy_decision = self.route_message(message)
        yield "chat-meta", {
            "routed_intent": routed_intent,
            "policy_decision": policy_decision,
            "action_card": self._action_card(routed_intent, policy_decision),
        }

        if policy_decision.get("action") == "stream_chat":
            for chunk in self._chat_responder.stream_reply(message):
                yield "chat-token", {"content": chunk}
            return

        reply = self._reply_for_policy(routed_intent, policy_decision)
        if reply:
            yield "chat-token", {"content": reply}

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

    def _reply_for_policy(self, routed_intent: JsonDict, policy_decision: JsonDict) -> str:
        action = policy_decision.get("action")
        if action == "ask_clarification":
            missing = routed_intent.get("missing_fields") or policy_decision.get("missing_fields") or []
            if "ticker" in missing:
                return "我需要一个股票代码才能开始研究。比如：分析 AAPL 最近的 10-K，重点看风险因素和现金流。"
            return "我还需要一点信息才能继续。请补充公司、数据来源或你希望的输出格式。"
        if action == "show_run_research_card":
            ticker = routed_intent.get("ticker")
            filing_type = routed_intent.get("filing_type") or "10-K"
            focus = ", ".join(routed_intent.get("focus") or []) or "general filing analysis"
            return f"我识别到一个 SEC filing 研究请求：{ticker} {filing_type}，重点：{focus}。确认后我再启动研究任务。"
        if action == "unsupported_response":
            return routed_intent.get("assistant_reply") or policy_decision.get("reason") or "这个能力还没有实现。"
        if action == "routing_error":
            return routed_intent.get("assistant_reply") or "LLM 意图识别失败。请检查模型配置后再试。"
        return routed_intent.get("assistant_reply") or ""

    def _action_card(self, routed_intent: JsonDict, policy_decision: JsonDict) -> Optional[JsonDict]:
        if policy_decision.get("action") != "show_run_research_card":
            return None
        return {
            "title": f"Analyze {routed_intent.get('ticker')} {routed_intent.get('filing_type') or '10-K'}",
            "skill_name": "sec_filing_analysis",
            "ticker": routed_intent.get("ticker"),
            "filing_type": routed_intent.get("filing_type") or "10-K",
            "focus": routed_intent.get("focus") or [],
            "requires_confirmation": True,
        }

    def _objective_from_routed_intent(self, message: str, routed_intent: JsonDict) -> str:
        focus = ", ".join(routed_intent.get("focus") or [])
        ticker = routed_intent.get("ticker")
        filing_type = routed_intent.get("filing_type") or "10-K"
        if focus:
            return f"Analyze {ticker} {filing_type}, focusing on {focus}. User request: {message}"
        return message.strip() or f"Analyze {ticker} {filing_type}"
