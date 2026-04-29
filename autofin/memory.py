from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


JsonDict = Dict[str, Any]


@dataclass
class SessionMemory:
    summary: str = ""
    working_entities: JsonDict = field(default_factory=dict)
    pending_action: JsonDict | None = None
    active_task_id: str | None = None
    task_summaries: List[JsonDict] = field(default_factory=list)

    def update_from_route(self, routed_intent: JsonDict, policy_decision: JsonDict) -> None:
        if routed_intent.get("intent"):
            self.working_entities["last_intent"] = routed_intent["intent"]
        if routed_intent.get("ticker"):
            self.working_entities["ticker"] = routed_intent["ticker"]
        if routed_intent.get("filing_type"):
            self.working_entities["filing_type"] = routed_intent["filing_type"]
        if routed_intent.get("focus"):
            self.working_entities["focus"] = routed_intent["focus"]

        if policy_decision.get("requires_confirmation"):
            self.pending_action = {
                "action": policy_decision.get("action"),
                "intent": routed_intent.get("intent"),
                "ticker": routed_intent.get("ticker"),
                "filing_type": routed_intent.get("filing_type"),
                "focus": routed_intent.get("focus") or [],
            }
        elif policy_decision.get("action") != "show_run_research_card":
            self.pending_action = None

    def set_active_task(self, task_id: str) -> None:
        self.active_task_id = task_id
        self.pending_action = None

    def add_task_summary(self, task_summary: JsonDict, max_items: int = 5) -> None:
        clean_summary = {key: value for key, value in task_summary.items() if value not in (None, "", [])}
        if not clean_summary:
            return
        self.task_summaries = [item for item in self.task_summaries if item.get("task_id") != clean_summary.get("task_id")]
        self.task_summaries.append(clean_summary)
        self.task_summaries = self.task_summaries[-max_items:]
        if clean_summary.get("ticker"):
            self.working_entities["ticker"] = clean_summary["ticker"]
        if clean_summary.get("filing_type"):
            self.working_entities["filing_type"] = clean_summary["filing_type"]

    def update_summary(self, messages: List[JsonDict], max_messages: int = 6) -> None:
        recent = messages[-max_messages:]
        parts = []
        for message in recent:
            content = str(message.get("content", "")).strip().replace("\n", " ")
            if not content:
                continue
            parts.append(f"{message.get('role', 'unknown')}: {content[:180]}")
        self.summary = "\n".join(parts)

    def to_prompt_context(self, recent_messages: List[JsonDict]) -> str:
        lines = ["Session memory:"]
        if self.summary:
            lines.append(f"Summary:\n{self.summary}")
        if self.working_entities:
            lines.append(f"Working entities: {self.working_entities}")
        if self.active_task_id:
            lines.append(f"Active task id: {self.active_task_id}")
        if self.pending_action:
            lines.append(f"Pending action: {self.pending_action}")
        if self.task_summaries:
            lines.append("Recent task summaries:")
            for task in self.task_summaries[-3:]:
                lines.append(f"- {task}")

        if recent_messages:
            lines.append("Recent messages:")
            for message in recent_messages[-6:]:
                content = str(message.get("content", "")).strip().replace("\n", " ")
                if content:
                    lines.append(f"- {message.get('role', 'unknown')}: {content[:240]}")
        return "\n".join(lines)

    def to_dict(self) -> JsonDict:
        return {
            "summary": self.summary,
            "working_entities": self.working_entities,
            "pending_action": self.pending_action,
            "active_task_id": self.active_task_id,
            "task_summaries": self.task_summaries,
        }

    @classmethod
    def from_dict(cls, payload: JsonDict | None) -> "SessionMemory":
        payload = payload or {}
        return cls(
            summary=str(payload.get("summary", "")),
            working_entities=dict(payload.get("working_entities") or {}),
            pending_action=payload.get("pending_action"),
            active_task_id=payload.get("active_task_id"),
            task_summaries=list(payload.get("task_summaries") or []),
        )
