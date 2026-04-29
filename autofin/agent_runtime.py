from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable

from autofin.intent import ChatResponder
from autofin.intent_router import IntentRouter
from autofin.policy import PolicyEngine, PolicyLogger
from autofin.session import SessionStore, make_message


JsonDict = Dict[str, Any]


@dataclass
class AgentRuntime:
    intent_router: IntentRouter
    policy_engine: PolicyEngine
    policy_logger: PolicyLogger
    chat_responder: ChatResponder
    session_store: SessionStore

    def list_sessions(self) -> list[JsonDict]:
        sessions = self.session_store.list_sessions()
        if sessions:
            return sessions
        return [self.session_store.create_session().public_view()]

    def get_session(self, session_id: str | None = None) -> JsonDict:
        session = self.session_store.get_or_create(session_id)
        return session.public_view(include_messages=True)

    def new_session(self) -> JsonDict:
        return self.session_store.create_session().public_view(include_messages=True)

    def delete_session(self, session_id: str) -> JsonDict:
        self.session_store.delete_session(session_id)
        sessions = self.list_sessions()
        active_session = sessions[0] if sessions else self.new_session()
        return {"deleted_session_id": session_id, "active_session": active_session, "sessions": self.list_sessions()}

    def delete_all_sessions(self) -> JsonDict:
        deleted_count = self.session_store.delete_all_sessions()
        active_session = self.new_session()
        return {"deleted_count": deleted_count, "active_session": active_session, "sessions": self.list_sessions()}

    def preview_chat(self, message: str, session_id: str | None = None) -> JsonDict:
        session = self.session_store.get_or_create(session_id)
        context = self.session_store.context_for(session.id)
        routed_intent, policy_decision = self.route_message(message, session.id, context)
        user_message = self._ensure_user_message(session.id, message, routed_intent, policy_decision)

        if policy_decision.get("action") == "stream_chat":
            reply, responder_metadata = self.chat_responder.reply(message, context)
            assistant_message = self.session_store.append_message(
                session.id,
                "assistant",
                reply,
                {
                    "routed_intent": routed_intent,
                    "policy_decision": policy_decision,
                    **responder_metadata,
                },
            )
        else:
            assistant_message = self.session_store.append_message(
                session.id,
                "assistant",
                self.reply_for_policy(routed_intent, policy_decision),
                {"routed_intent": routed_intent, "policy_decision": policy_decision},
            )

        return {
            "session": self.session_store.public_view(session.id, include_messages=True),
            "session_id": session.id,
            "user_message": user_message,
            "assistant_message": assistant_message,
            "routed_intent": routed_intent,
            "policy_decision": policy_decision,
            "action_card": self.action_card(routed_intent, policy_decision),
        }

    def stream_chat_events(self, message: str, session_id: str | None = None) -> Iterable[tuple[str, JsonDict]]:
        session = self.session_store.get_or_create(session_id)
        context = self.session_store.context_for(session.id)
        routed_intent, policy_decision = self.route_message(message, session.id, context)
        self._ensure_user_message(session.id, message, routed_intent, policy_decision)
        yield "chat-meta", {
            "session": self.session_store.public_view(session.id),
            "session_id": session.id,
            "routed_intent": routed_intent,
            "policy_decision": policy_decision,
            "action_card": self.action_card(routed_intent, policy_decision),
        }

        if policy_decision.get("action") == "stream_chat":
            content = ""
            for chunk in self.chat_responder.stream_reply(message, context):
                content += chunk
                yield "chat-token", {"content": chunk}
            self.session_store.append_message(
                session.id,
                "assistant",
                content,
                {"routed_intent": routed_intent, "policy_decision": policy_decision},
            )
            return

        reply = self.reply_for_policy(routed_intent, policy_decision)
        if reply:
            yield "chat-token", {"content": reply}
            self.session_store.append_message(
                session.id,
                "assistant",
                reply,
                {"routed_intent": routed_intent, "policy_decision": policy_decision},
            )

    def prepare_research_run(self, message: str, session_id: str | None = None) -> JsonDict:
        session = self.session_store.get_or_create(session_id)
        context = self.session_store.context_for(session.id)
        routed_intent, policy_decision = self.route_message(message, session.id, context)
        self._ensure_user_message(session.id, message, routed_intent, policy_decision)
        return {
            "session": self.session_store.public_view(session.id),
            "session_id": session.id,
            "routed_intent": routed_intent,
            "policy_decision": policy_decision,
            "action_card": self.action_card(routed_intent, policy_decision),
        }

    def record_research_task_created(
        self,
        session_id: str,
        task_id: str,
        assistant_content: str,
        routed_intent: JsonDict,
        policy_decision: JsonDict,
    ) -> JsonDict:
        policy_decision["created_task_id"] = task_id
        self.session_store.set_active_task(session_id, task_id)
        assistant_message = self.session_store.append_message(
            session_id,
            "assistant",
            assistant_content,
            {"ticker": routed_intent.get("ticker"), "filing_type": routed_intent.get("filing_type")},
        )
        self.policy_logger.log(
            "",
            routed_intent,
            policy_decision,
            {"user_clicked_run": True, "created_task_id": task_id, "session_id": session_id},
        )
        return assistant_message

    def route_message(self, message: str, session_id: str, context: str) -> tuple[JsonDict, JsonDict]:
        routed_intent = self.intent_router.route(message, context=context)
        routed_intent = self._resolve_from_session_memory(session_id, routed_intent)
        policy_decision = self.policy_engine.decide(routed_intent)
        self.session_store.update_memory_from_route(session_id, routed_intent, policy_decision)
        self.policy_logger.log(
            message,
            routed_intent,
            policy_decision,
            {"session_id": session_id},
        )
        return routed_intent, policy_decision

    def _resolve_from_session_memory(self, session_id: str, routed_intent: JsonDict) -> JsonDict:
        session = self.session_store.get(session_id)
        memory = session.memory
        resolved = dict(routed_intent)
        resolved_fields = []

        if resolved.get("intent") == "research_sec_filing":
            entities = memory.working_entities
            missing_fields = list(resolved.get("missing_fields") or [])
            if not resolved.get("ticker") and entities.get("ticker"):
                resolved["ticker"] = entities["ticker"]
                resolved_fields.append("ticker")
            if not resolved.get("filing_type") and entities.get("filing_type"):
                resolved["filing_type"] = entities["filing_type"]
                resolved_fields.append("filing_type")
            if not resolved.get("focus") and entities.get("focus"):
                resolved["focus"] = entities["focus"]
                resolved_fields.append("focus")

            if resolved.get("ticker") and "ticker" in missing_fields:
                missing_fields.remove("ticker")
            if resolved.get("filing_type") and "filing_type" in missing_fields:
                missing_fields.remove("filing_type")
            resolved["missing_fields"] = missing_fields
            if resolved.get("ticker") and not missing_fields:
                resolved["needs_confirmation"] = True

        if resolved.get("intent") == "write_report":
            missing_fields = list(resolved.get("missing_fields") or [])
            source_task_id = memory.active_task_id
            if not source_task_id and memory.task_summaries:
                source_task_id = memory.task_summaries[-1].get("task_id")
            if source_task_id:
                resolved["source_task_id"] = source_task_id
                resolved_fields.append("source_task_id")
                if "source_task" in missing_fields:
                    missing_fields.remove("source_task")
                resolved["missing_fields"] = missing_fields

        if resolved_fields:
            resolved["resolved_from_memory"] = resolved_fields
        return resolved

    def reply_for_policy(self, routed_intent: JsonDict, policy_decision: JsonDict) -> str:
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

    def action_card(self, routed_intent: JsonDict, policy_decision: JsonDict) -> JsonDict | None:
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

    def _ensure_user_message(
        self,
        session_id: str,
        message: str,
        routed_intent: JsonDict,
        policy_decision: JsonDict,
    ) -> JsonDict:
        session = self.session_store.get(session_id)
        if session.messages and session.messages[-1].get("role") == "user" and session.messages[-1].get("content") == message:
            return session.messages[-1]
        return self.session_store.append_message(
            session_id,
            "user",
            message,
            {"routed_intent": routed_intent, "policy_decision": policy_decision},
        )

    def message(self, role: str, content: str, metadata: JsonDict | None = None) -> JsonDict:
        return make_message(role, content, metadata)
