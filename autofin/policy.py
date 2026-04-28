from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict
from uuid import uuid4

from pydantic import BaseModel, Field


JsonDict = Dict[str, Any]


class PolicyDecision(BaseModel):
    decision_id: str = Field(default_factory=lambda: str(uuid4()))
    intent: str
    confidence: float
    action: str
    reason: str
    requires_confirmation: bool = False
    missing_fields: list[str] = Field(default_factory=list)
    created_task_id: str | None = None


@dataclass
class PolicyEngine:
    def decide(self, routed_intent: JsonDict) -> JsonDict:
        intent = routed_intent.get("intent", "unknown")
        confidence = float(routed_intent.get("confidence", 0))
        missing_fields = list(routed_intent.get("missing_fields") or [])

        if intent in {"general_chat", "explain_app", "configure_settings"}:
            return PolicyDecision(
                intent=intent,
                confidence=confidence,
                action="stream_chat",
                reason="Non-executable intent should be answered as conversation.",
            ).model_dump()

        if intent == "research_sec_filing":
            if missing_fields:
                return PolicyDecision(
                    intent=intent,
                    confidence=confidence,
                    action="ask_clarification",
                    reason="SEC filing research requires a ticker before creating a task.",
                    missing_fields=missing_fields,
                ).model_dump()
            return PolicyDecision(
                intent=intent,
                confidence=confidence,
                action="show_run_research_card",
                reason="Research request is executable, but task execution should be explicit.",
                requires_confirmation=True,
            ).model_dump()

        if intent in {"research_market_data", "research_news", "compare_companies", "write_report"}:
            return PolicyDecision(
                intent=intent,
                confidence=confidence,
                action="unsupported_response",
                reason=routed_intent.get("unsupported_reason") or f"{intent} is not implemented yet.",
                missing_fields=missing_fields,
            ).model_dump()

        if intent == "intent_routing_failed":
            return PolicyDecision(
                intent=intent,
                confidence=confidence,
                action="routing_error",
                reason=routed_intent.get("unsupported_reason") or "LLM intent routing failed.",
            ).model_dump()

        return PolicyDecision(
            intent="unknown",
            confidence=confidence,
            action="ask_clarification",
            reason="Intent is unknown or confidence is too low.",
            missing_fields=missing_fields,
        ).model_dump()


@dataclass
class PolicyLogger:
    path: Path
    enabled: bool = True

    def __post_init__(self) -> None:
        self._lock = Lock()

    def log(self, message: str, routed_intent: JsonDict, policy_decision: JsonDict, outcome: JsonDict | None = None) -> None:
        if not self.enabled:
            return
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "message": message,
            "routed_intent": routed_intent,
            "policy_decision": policy_decision,
            "outcome": outcome or {},
        }
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._lock:
                with self.path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(event, ensure_ascii=False) + "\n")
        except OSError:
            return
