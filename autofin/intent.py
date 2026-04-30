from __future__ import annotations

import re
import json
from dataclasses import dataclass, field
from typing import Iterable, Optional, Protocol

from pydantic import BaseModel, Field

from autofin.config import JsonDict, ModelAPIConfig, ModelConfigStore


class ResearchIntent(BaseModel):
    intent_type: str = Field(
        default="research_task",
        description="Either research_task for executable financial research or conversation for general chat.",
    )
    ticker: str | None = Field(default=None, description="Stock ticker symbol, e.g. AAPL.")
    filing_type: str | None = Field(default="10-K", description="SEC filing type, usually 10-K or 10-Q.")
    objective: str = Field(description="The user's research objective.")
    focus: list[str] = Field(default_factory=list, description="Research focus areas.")
    reply: str = Field(default="", description="Assistant reply for general conversation.")

    def normalized(self) -> JsonDict:
        intent_type = self.intent_type if self.intent_type in {"research_task", "conversation"} else "research_task"
        ticker = self.ticker.upper().strip() if self.ticker else None
        filing_type = (self.filing_type or "10-K").upper().replace(" ", "-")
        if filing_type not in {"10-K", "10-Q"}:
            filing_type = "10-K"
        return {
            "intent_type": intent_type,
            "ticker": ticker,
            "filing_type": filing_type,
            "objective": self.objective.strip() or "Analyze SEC filing",
            "focus": list(self.focus),
            "reply": self.reply.strip(),
        }


class IntentParser(Protocol):
    def parse(self, message: str) -> JsonDict:
        ...


class ChatResponder(Protocol):
    def reply(self, message: str, context: str = "") -> tuple[str, JsonDict]:
        ...

    def stream_reply(self, message: str, context: str = "") -> Iterable[str]:
        ...


@dataclass
class DeterministicIntentParser:
    def parse(self, message: str) -> JsonDict:
        if self._is_general_conversation(message):
            return ResearchIntent(
                intent_type="conversation",
                ticker=None,
                filing_type="10-K",
                objective=message.strip() or "General conversation",
                focus=[],
                reply=self._general_reply(message),
            ).normalized()

        filing_match = re.search(r"\b(10[- ]?[KQ])\b", message, flags=re.IGNORECASE)
        filing_type = filing_match.group(1).replace(" ", "-").upper() if filing_match else "10-K"

        ticker = None
        ticker_text = re.sub(r"\b10[- ]?[KQ]\b", " ", message, flags=re.IGNORECASE)
        ignored = {"SEC", "API", "MD", "AI", "UI", "CEO", "CFO", "USD"}
        for match in re.finditer(r"\b[A-Z]{1,5}\b", ticker_text):
            candidate = match.group(0)
            if candidate not in ignored and not candidate.startswith("10"):
                ticker = candidate
                break

        focus = []
        lowered = message.lower()
        if "risk" in lowered or "风险" in message:
            focus.append("risk factors")
        if "cash" in lowered or "现金流" in message:
            focus.append("cash flow")
        if "revenue" in lowered or "收入" in message:
            focus.append("revenue")
        if "memo" in lowered or "报告" in message:
            focus.append("memo")

        return ResearchIntent(
            intent_type="research_task",
            ticker=ticker,
            filing_type=filing_type,
            objective=message.strip() or "Analyze SEC filing",
            focus=focus,
        ).normalized()

    def _is_general_conversation(self, message: str) -> bool:
        text = message.strip().lower()
        if not text:
            return True
        research_markers = [
            "10-k",
            "10 q",
            "10-q",
            "filing",
            "sec",
            "risk",
            "cash flow",
            "revenue",
            "analyze",
            "分析",
            "财报",
            "年报",
            "季报",
            "风险",
            "现金流",
            "收入",
        ]
        if any(marker in text or marker in message for marker in research_markers):
            return False
        return not bool(re.search(r"\b[A-Z]{1,5}\b", message))

    def _general_reply(self, message: str) -> str:
        if not message.strip():
            return "你可以直接告诉我想研究的公司和问题，例如：分析 AAPL 最近的 10-K，重点看风险因素和现金流。"
        if any(token in message.lower() for token in ["hello", "hi"]) or any(
            token in message for token in ["你好", "您好"]
        ):
            return "你好，我可以帮你做金融研究、SEC filing 分析、证据追踪和报告整理。你也可以先随便问我项目怎么用。"
        return "我在。你可以和我普通对话，也可以让我创建金融研究任务；如果要执行研究，请告诉我公司 ticker 和研究重点。"


@dataclass
class DeterministicChatResponder:
    def reply(self, message: str, context: str = "") -> tuple[str, JsonDict]:
        research_reply = self._research_context_reply(message, context)
        if research_reply:
            return research_reply, {"responder": "deterministic_research_context"}
        parser = DeterministicIntentParser()
        return parser._general_reply(message), {"responder": "deterministic"}

    def stream_reply(self, message: str, context: str = "") -> Iterable[str]:
        yield self.reply(message, context)[0]

    def _research_context_reply(self, message: str, context: str) -> str:
        if "Active research context:" not in context:
            return ""
        citation_match = re.search(r"\b(E\d+)\b", message, flags=re.IGNORECASE)
        if citation_match:
            citation = citation_match.group(1).upper()
            evidence_line = self._find_context_line(context, f"[{citation}]")
            if evidence_line:
                return f"{citation} 对应的证据是：{evidence_line.lstrip('- ').strip()}"
            return f"当前研究上下文里没有找到 [{citation}] 对应证据。"

        lowered = message.lower()
        if "风险" in message or "risk" in lowered:
            risks = self._context_section(context, "Risk watchlist:", "Evidence references:")
            if risks:
                return "基于当前报告，主要风险包括：\n" + "\n".join(risks[:4])
            return "当前报告里没有足够的 risk watchlist 信息。"

        if any(token in message for token in ["总结", "三点", "结论"]) or any(
            token in lowered for token in ["summarize", "summary", "conclusion"]
        ):
            observations = self._context_section(context, "Key observations:", "Risk watchlist:")
            if observations:
                return "基于当前报告，可以总结为：\n" + "\n".join(observations[:3])
            summary = self._find_context_line(context, "Executive summary:")
            if summary:
                return summary.replace("Executive summary:", "基于当前报告：", 1)
            return "当前报告上下文不足，无法可靠总结。"

        if any(token in message for token in ["证据", "来源"]) or any(token in lowered for token in ["evidence", "source"]):
            evidence = self._context_section(context, "Evidence references:", "")
            if evidence:
                return "当前报告可追溯到这些证据：\n" + "\n".join(evidence[:5])
            return "当前报告上下文里没有可用证据引用。"

        return ""

    def _find_context_line(self, context: str, needle: str) -> str:
        for line in context.splitlines():
            if needle in line:
                return line.strip()
        return ""

    def _context_section(self, context: str, start: str, end: str) -> list[str]:
        lines = context.splitlines()
        collecting = False
        section = []
        for line in lines:
            if line.strip() == start:
                collecting = True
                continue
            if collecting and end and line.strip() == end:
                break
            if collecting and line.startswith("- "):
                section.append(line.strip())
        return section


@dataclass
class LangChainChatResponder:
    model_config_store: ModelConfigStore
    fallback: ChatResponder = field(default_factory=DeterministicChatResponder)

    def reply(self, message: str, context: str = "") -> tuple[str, JsonDict]:
        config = self.model_config_store.get()
        if not self._is_configured(config):
            reply, metadata = self.fallback.reply(message, context)
            return reply, {**metadata, "responder": "deterministic"}

        try:
            llm = self._build_llm(config)
            response = llm.invoke(
                [
                    self._system_message(
                        "You are AutoFinResearchAgent, a local-first financial research assistant. "
                        "Answer normal conversation naturally and concisely. "
                        "When Active research context is provided, answer follow-up questions from that context only, "
                        "cite evidence ids like [E1], and say when the report lacks enough evidence. "
                        "For requests that need financial research execution, tell the user to include a ticker and focus. "
                        f"Use this session context when relevant:\n{context}"
                    ),
                    self._human_message(message),
                ]
            )
            content = getattr(response, "content", str(response))
            return str(content), {"responder": "langchain"}
        except Exception as exc:
            reply, metadata = self.fallback.reply(message, context)
            return reply, {**metadata, "responder": "deterministic_fallback", "responder_error": str(exc)}

    def stream_reply(self, message: str, context: str = "") -> Iterable[str]:
        config = self.model_config_store.get()
        if not self._is_configured(config):
            yield from self.fallback.stream_reply(message, context)
            return

        try:
            llm = self._build_llm(config)
            for chunk in llm.stream(
                [
                    self._system_message(
                        "You are AutoFinResearchAgent, a local-first financial research assistant. "
                        "Answer normal conversation naturally and concisely. "
                        "When Active research context is provided, answer follow-up questions from that context only, "
                        "cite evidence ids like [E1], and say when the report lacks enough evidence. "
                        "For requests that need financial research execution, tell the user to include a ticker and focus. "
                        f"Use this session context when relevant:\n{context}"
                    ),
                    self._human_message(message),
                ]
            ):
                content = getattr(chunk, "content", "")
                if content:
                    yield str(content)
        except Exception:
            yield from self.fallback.stream_reply(message, context)

    def _build_llm(self, config: ModelAPIConfig):
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("langchain-openai is required for model-backed chat") from exc

        model_kwargs = {
            "model": config.model,
            "api_key": config.api_key,
            "temperature": config.temperature,
        }
        if config.base_url:
            model_kwargs["base_url"] = config.base_url
        return ChatOpenAI(**model_kwargs)

    def _system_message(self, content: str):
        from langchain_core.messages import SystemMessage

        return SystemMessage(content=content)

    def _human_message(self, content: str):
        from langchain_core.messages import HumanMessage

        return HumanMessage(content=content)

    def _is_configured(self, config: ModelAPIConfig) -> bool:
        return bool(config.model and config.api_key)


@dataclass
class LangChainIntentParser:
    model_config_store: ModelConfigStore
    fallback: IntentParser = field(default_factory=DeterministicIntentParser)

    def parse(self, message: str) -> JsonDict:
        config = self.model_config_store.get()
        precheck = self.fallback.parse(message)
        if precheck.get("intent_type") == "conversation":
            precheck["parser"] = "deterministic_precheck"
            return precheck

        if not self._is_configured(config):
            precheck["parser"] = "deterministic"
            return precheck

        try:
            intent = self._parse_with_langchain(message, config)
            parsed = intent.normalized()
            parsed["parser"] = "langchain"
            return parsed
        except Exception as exc:
            precheck["parser"] = "deterministic_fallback"
            precheck["parser_error"] = str(exc)
            return precheck

    def _parse_with_langchain(self, message: str, config: ModelAPIConfig) -> ResearchIntent:
        try:
            return self._parse_with_structured_output(message, config)
        except Exception:
            return self._parse_with_json_prompt(message, config)

    def _parse_with_structured_output(self, message: str, config: ModelAPIConfig) -> ResearchIntent:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("langchain-openai is required for model-backed parsing") from exc

        model_kwargs = {
            "model": config.model,
            "api_key": config.api_key,
            "temperature": config.temperature,
        }
        if config.base_url:
            model_kwargs["base_url"] = config.base_url

        llm = ChatOpenAI(**model_kwargs)
        structured_llm = llm.with_structured_output(ResearchIntent)
        result = structured_llm.invoke(
            [
                SystemMessage(
                    content=(
                        "Extract a structured financial research intent from the user message. "
                        "Set intent_type to conversation for general chat, usage questions, greetings, "
                        "or messages that do not ask to run financial research. "
                        "Only return a ticker when the user clearly names one. "
                        "Use filing_type 10-K or 10-Q when mentioned; otherwise default to 10-K. "
                        "For conversation, include a concise helpful reply."
                    )
                ),
                HumanMessage(content=message),
            ]
        )
        if isinstance(result, ResearchIntent):
            return result
        return ResearchIntent.model_validate(result)

    def _parse_with_json_prompt(self, message: str, config: ModelAPIConfig) -> ResearchIntent:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("langchain-openai is required for model-backed parsing") from exc

        model_kwargs = {
            "model": config.model,
            "api_key": config.api_key,
            "temperature": 0,
        }
        if config.base_url:
            model_kwargs["base_url"] = config.base_url

        llm = ChatOpenAI(**model_kwargs)
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "Return only valid JSON for this schema: "
                        "{\"intent_type\":\"conversation|research_task\","
                        "\"ticker\":null,\"filing_type\":\"10-K|10-Q\","
                        "\"objective\":\"string\",\"focus\":[\"string\"],\"reply\":\"string\"}. "
                        "Use conversation for general chat. Use research_task only when the user asks to run financial research."
                    )
                ),
                HumanMessage(content=message),
            ]
        )
        content = str(getattr(response, "content", response)).strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE | re.DOTALL)
        return ResearchIntent.model_validate(json.loads(content))

    def _is_configured(self, config: ModelAPIConfig) -> bool:
        return bool(config.model and config.api_key)
