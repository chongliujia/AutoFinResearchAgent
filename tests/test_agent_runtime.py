from pathlib import Path

from autofin.agent_runtime import AgentRuntime
from autofin.intent import DeterministicChatResponder
from autofin.policy import PolicyEngine, PolicyLogger
from autofin.session import SessionStore


class MissingTickerFollowUpRouter:
    def route(self, message: str, context: str = ""):
        return {
            "intent": "research_sec_filing",
            "confidence": 0.86,
            "assistant_reply": "",
            "ticker": None,
            "company_names": [],
            "filing_type": None,
            "focus": ["cash flow"],
            "time_range": None,
            "output_format": None,
            "missing_fields": ["ticker"],
            "needs_confirmation": False,
            "unsupported_reason": None,
            "router": "fake_llm",
        }


class ReportFollowUpRouter:
    def route(self, message: str, context: str = ""):
        return {
            "intent": "write_report",
            "confidence": 0.9,
            "assistant_reply": "",
            "ticker": None,
            "company_names": [],
            "filing_type": None,
            "focus": [],
            "time_range": None,
            "output_format": "memo",
            "missing_fields": ["source_task"],
            "needs_confirmation": False,
            "unsupported_reason": "report writing is not implemented yet",
            "router": "fake_llm",
        }


def build_runtime(router, tmp_path: Path):
    return AgentRuntime(
        intent_router=router,
        policy_engine=PolicyEngine(),
        policy_logger=PolicyLogger(tmp_path / "policy.jsonl", enabled=False),
        chat_responder=DeterministicChatResponder(),
        session_store=SessionStore(persist=False),
    )


def test_runtime_resolves_research_follow_up_from_session_memory(tmp_path):
    runtime = build_runtime(MissingTickerFollowUpRouter(), tmp_path)
    session = runtime.session_store.create_session()
    runtime.session_store.update_memory_from_route(
        session.id,
        {"intent": "research_sec_filing", "ticker": "AAPL", "filing_type": "10-K", "focus": ["risk factors"]},
        {"action": "show_run_research_card", "requires_confirmation": True},
    )

    result = runtime.preview_chat("继续刚才那个，重点看现金流", session.id)

    assert result["routed_intent"]["ticker"] == "AAPL"
    assert result["routed_intent"]["filing_type"] == "10-K"
    assert result["routed_intent"]["focus"] == ["cash flow"]
    assert result["routed_intent"]["missing_fields"] == []
    assert result["routed_intent"]["resolved_from_memory"] == ["ticker", "filing_type"]
    assert result["policy_decision"]["action"] == "show_run_research_card"


def test_runtime_resolves_report_source_task_from_memory(tmp_path):
    runtime = build_runtime(ReportFollowUpRouter(), tmp_path)
    session = runtime.session_store.create_session()
    runtime.session_store.set_active_task(session.id, "task-123")

    result = runtime.preview_chat("整理成 memo", session.id)

    assert result["routed_intent"]["source_task_id"] == "task-123"
    assert result["routed_intent"]["missing_fields"] == []
    assert result["routed_intent"]["resolved_from_memory"] == ["source_task_id"]
