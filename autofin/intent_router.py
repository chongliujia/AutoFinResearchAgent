from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel, Field, field_validator

from autofin.config import JsonDict, ModelAPIConfig, ModelConfigStore


SUPPORTED_INTENTS = {
    "general_chat",
    "explain_app",
    "configure_settings",
    "research_qa",
    "research_sec_filing",
    "research_market_data",
    "research_news",
    "compare_companies",
    "write_report",
    "intent_routing_failed",
    "unknown",
}


class RoutedIntent(BaseModel):
    intent: str = Field(default="general_chat")
    confidence: float = Field(default=0.5, ge=0, le=1)
    assistant_reply: str = ""
    ticker: str | None = None
    company_names: list[str] = Field(default_factory=list)
    filing_type: str | None = None
    focus: list[str] = Field(default_factory=list)
    time_range: str | None = None
    output_format: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    needs_confirmation: bool = False
    unsupported_reason: str | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _coerce_confidence(cls, value):
        if isinstance(value, str):
            normalized = value.strip().lower()
            labels = {"high": 0.9, "medium": 0.6, "low": 0.3}
            if normalized in labels:
                return labels[normalized]
            if normalized.endswith("%"):
                return float(normalized[:-1]) / 100
        return value

    @field_validator("ticker", "filing_type", "time_range", "output_format", "unsupported_reason", mode="before")
    @classmethod
    def _coerce_optional_string(cls, value):
        if value is None or value == "":
            return None
        if isinstance(value, list):
            return str(value[0]) if value else None
        if isinstance(value, dict) and not value:
            return None
        return value

    @field_validator("company_names", "focus", "missing_fields", mode="before")
    @classmethod
    def _coerce_string_list(cls, value):
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in re.split(r"[,;，；]", value) if item.strip()]
        return value

    def normalized(self) -> JsonDict:
        intent = self.intent if self.intent in SUPPORTED_INTENTS else "unknown"
        ticker = self.ticker.upper().strip() if self.ticker else None
        filing_type = self.filing_type.upper().replace(" ", "-") if self.filing_type else None
        if filing_type not in {"10-K", "10-Q", None}:
            filing_type = None
        missing_fields = list(dict.fromkeys(self.missing_fields))
        if intent == "research_sec_filing" and not ticker and "ticker" not in missing_fields:
            missing_fields.append("ticker")
        return {
            "intent": intent,
            "confidence": round(float(self.confidence), 3),
            "assistant_reply": self.assistant_reply.strip(),
            "ticker": ticker,
            "company_names": [name.strip() for name in self.company_names if name.strip()],
            "filing_type": filing_type,
            "focus": [item.strip() for item in self.focus if item.strip()],
            "time_range": self.time_range,
            "output_format": self.output_format,
            "missing_fields": missing_fields,
            "needs_confirmation": bool(self.needs_confirmation),
            "unsupported_reason": self.unsupported_reason,
        }


class IntentRouter(Protocol):
    def route(self, message: str, context: str = "") -> JsonDict:
        ...


@dataclass
class DeterministicIntentRouter:
    def route(self, message: str, context: str = "") -> JsonDict:
        text = message.strip()
        lowered = text.lower()
        tickers = self._extract_tickers(text)
        filing_type = self._extract_filing_type(text)
        focus = self._extract_focus(text)

        if not text:
            return self._with_router(
                RoutedIntent(
                    intent="general_chat",
                    confidence=0.92,
                    assistant_reply="你可以直接输入普通问题，也可以输入带 ticker 的研究请求。",
                )
            )

        if self._contains_any(lowered, text, ["api key", "base url", "model api", "模型", "配置", "密钥"]):
            return self._with_router(
                RoutedIntent(
                    intent="configure_settings",
                    confidence=0.78,
                    assistant_reply="模型和 API key 可以在左侧 Model API 面板配置，密钥会保存在本地 .autofin/secrets.json。",
                )
            )

        if self._contains_any(lowered, text, ["怎么用", "如何使用", "evidence", "timeline", "ui", "界面", "项目"]):
            return self._with_router(
                RoutedIntent(
                    intent="explain_app",
                    confidence=0.75,
                    assistant_reply="这是一个本地优先的金融研究 agent。聊天区负责对话，研究任务会在右侧展示执行过程、结果和证据。",
                )
            )

        if self._looks_like_research_followup(lowered, text, context):
            return self._with_router(
                RoutedIntent(
                    intent="research_qa",
                    confidence=0.8,
                    assistant_reply="我会基于当前研究任务的 report 和 evidence 回答。",
                )
            )

        if self._contains_any(lowered, text, ["新闻", "news", "监管", "催化剂", "事件"]):
            return self._with_router(
                RoutedIntent(
                    intent="research_news",
                    confidence=0.72,
                    ticker=tickers[0] if tickers else None,
                    unsupported_reason="news skill is not implemented yet",
                    assistant_reply="新闻研究 skill 还没有实现。当前可以先做 SEC filing 分析。",
                )
            )

        if self._contains_any(lowered, text, ["股价", "行情", "price", "pe", "估值", "市值"]):
            return self._with_router(
                RoutedIntent(
                    intent="research_market_data",
                    confidence=0.72,
                    ticker=tickers[0] if tickers else None,
                    unsupported_reason="market data skill is not implemented yet",
                    assistant_reply="行情和估值数据 skill 还没有实现。当前可以先做 SEC filing 分析。",
                )
            )

        if self._contains_any(lowered, text, ["比较", "compare"]) and len(tickers) >= 2:
            return self._with_router(
                RoutedIntent(
                    intent="compare_companies",
                    confidence=0.74,
                    ticker=tickers[0],
                    company_names=tickers[1:],
                    filing_type=filing_type,
                    focus=focus,
                    unsupported_reason="comparison workflow is not implemented yet",
                    assistant_reply="多公司比较工作流还没有实现。可以先分别运行单公司 SEC filing 分析。",
                )
            )

        if self._contains_any(lowered, text, ["memo", "markdown", "报告", "整理成", "write report"]):
            return self._with_router(
                RoutedIntent(
                    intent="write_report",
                    confidence=0.7,
                    output_format="markdown" if "markdown" in lowered else "memo",
                    missing_fields=["source_task"],
                    assistant_reply="报告生成需要先选择已有研究任务或数据来源。",
                )
            )

        if self._looks_like_sec_research(lowered, text, filing_type):
            ticker = tickers[0] if tickers else None
            missing_fields = [] if ticker else ["ticker"]
            return self._with_router(
                RoutedIntent(
                    intent="research_sec_filing",
                    confidence=0.82 if ticker else 0.68,
                    ticker=ticker,
                    filing_type=filing_type or "10-K",
                    focus=focus,
                    time_range="latest" if self._contains_any(lowered, text, ["最近", "latest"]) else None,
                    missing_fields=missing_fields,
                    needs_confirmation=bool(ticker),
                )
            )

        return self._with_router(
            RoutedIntent(
                intent="general_chat",
                confidence=0.64,
                assistant_reply="我在。你可以和我普通对话，也可以让我创建金融研究任务。",
            )
        )

    def _with_router(self, routed_intent: RoutedIntent) -> JsonDict:
        routed = routed_intent.normalized()
        routed["router"] = "deterministic"
        return routed

    def _extract_tickers(self, message: str) -> list[str]:
        ignored = {"SEC", "API", "MD", "AI", "UI", "CEO", "CFO", "USD", "URL", "PE"}
        ticker_text = re.sub(r"\b10[- ]?[KQ]\b", " ", message, flags=re.IGNORECASE)
        tickers = []
        for match in re.finditer(r"\b[A-Z]{1,5}\b", ticker_text):
            candidate = match.group(0)
            if candidate not in ignored and not candidate.startswith("10"):
                tickers.append(candidate)
        return list(dict.fromkeys(tickers))

    def _extract_filing_type(self, message: str) -> str | None:
        filing_match = re.search(r"\b(10[- ]?[KQ])\b", message, flags=re.IGNORECASE)
        if filing_match:
            return filing_match.group(1).replace(" ", "-").upper()
        if "年报" in message:
            return "10-K"
        if "季报" in message:
            return "10-Q"
        return None

    def _extract_focus(self, message: str) -> list[str]:
        lowered = message.lower()
        focus = []
        if "risk" in lowered or "风险" in message:
            focus.append("risk factors")
        if "cash" in lowered or "现金流" in message:
            focus.append("cash flow")
        if "revenue" in lowered or "收入" in message:
            focus.append("revenue")
        if "margin" in lowered or "利润率" in message:
            focus.append("margin")
        return focus

    def _looks_like_sec_research(self, lowered: str, message: str, filing_type: str | None) -> bool:
        markers = [
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
        return bool(filing_type) or self._contains_any(lowered, message, markers)

    def _looks_like_research_followup(self, lowered: str, message: str, context: str) -> bool:
        if "Active research context:" not in context:
            return False
        if re.search(r"\b[A-Z]{1,5}\b", message) and self._contains_any(lowered, message, ["分析", "analyze", "10-k", "10-q"]):
            return False
        markers = [
            "这个公司",
            "这家公司",
            "这个报告",
            "刚才",
            "主要风险",
            "风险是什么",
            "解释",
            "证据",
            "结论",
            "总结",
            "三点",
            "来源",
            "citation",
            "evidence",
            "risk",
            "summarize",
            "explain",
        ]
        return bool(re.search(r"\bE\d+\b", message)) or self._contains_any(lowered, message, markers)

    def _contains_any(self, lowered: str, original: str, markers: list[str]) -> bool:
        return any(marker in lowered or marker in original for marker in markers)


@dataclass
class LLMIntentRouter:
    model_config_store: ModelConfigStore

    def route(self, message: str, context: str = "") -> JsonDict:
        config = self.model_config_store.get()
        if not self._is_configured(config):
            routed = RoutedIntent(
                intent="configure_settings",
                confidence=1,
                assistant_reply="需要先配置 Model API，才能使用 LLM 意图识别。请在左侧 Model API 面板填写模型、Base URL 和 API Key。",
                unsupported_reason="model api is not configured",
            ).normalized()
            routed["router"] = "unconfigured"
            return routed

        try:
            routed = self._route_with_langchain(message, config, context).normalized()
            routed["router"] = "langchain"
            return routed
        except Exception as exc:
            routed = RoutedIntent(
                intent="intent_routing_failed",
                confidence=0,
                assistant_reply="LLM 意图识别失败。请检查模型配置、网络或模型输出格式后再试。",
                unsupported_reason="llm intent routing failed",
            ).normalized()
            routed["router"] = "langchain_error"
            routed["router_error"] = str(exc)
            return routed

    def _route_with_langchain(self, message: str, config: ModelAPIConfig, context: str = "") -> RoutedIntent:
        return self._route_with_json_prompt(message, config, context)

    def _route_with_structured_output(self, message: str, config: ModelAPIConfig, context: str = "") -> RoutedIntent:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("langchain-openai is required for model-backed routing") from exc

        llm = ChatOpenAI(**self._model_kwargs(config))
        structured_llm = llm.with_structured_output(RoutedIntent)
        result = structured_llm.invoke(
            [SystemMessage(content=self._system_prompt(context)), HumanMessage(content=message)]
        )
        if isinstance(result, RoutedIntent):
            return result
        return RoutedIntent.model_validate(result)

    def _route_with_json_prompt(self, message: str, config: ModelAPIConfig, context: str = "") -> RoutedIntent:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("langchain-openai is required for model-backed routing") from exc

        llm = ChatOpenAI(**self._model_kwargs(config, temperature=0))
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        f"{self._system_prompt(context)} Return only valid JSON. "
                        "Schema fields: intent, confidence, assistant_reply, ticker, company_names, "
                        "filing_type, focus, time_range, output_format, missing_fields, "
                        "needs_confirmation, unsupported_reason. "
                        "confidence must be a number between 0 and 1, not a word. "
                        "Use null for absent scalar fields. Use [] for absent list fields."
                    )
                ),
                HumanMessage(content=message),
            ]
        )
        content = str(getattr(response, "content", response)).strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE | re.DOTALL)
        return RoutedIntent.model_validate(json.loads(content))

    def _system_prompt(self, context: str = "") -> str:
        prompt = (
            "You are an intent router for a local financial research agent. "
            "Classify the user message into exactly one intent from: "
            f"{', '.join(sorted(SUPPORTED_INTENTS))}. "
            "Extract fields only; do not run tools and do not fabricate data. "
            "Use general_chat for ordinary conversation. "
            "Use research_qa when the user asks a follow-up about the active report, evidence ids, citations, conclusions, risks, or summary in session context. "
            "If the user asks to analyze a public stock or company without naming a data source, "
            "classify it as research_sec_filing and default filing_type to 10-K because that is the currently available executable research workflow. "
            "Use research_sec_filing only for SEC filing, 10-K, 10-Q, annual report, quarterly report, "
            "risk factor, cash flow, revenue, MD&A, filing analysis requests, or general public-company stock analysis requests. "
            "Set missing_fields when required fields are absent. "
            "Set needs_confirmation true for executable research workflows. "
            "Return confidence as a numeric value from 0 to 1. "
            "Return ticker as a string or null, never as a list."
        )
        if context:
            prompt += (
                " Use the session context to resolve follow-up phrases like "
                "'继续刚才那个', 'that company', 'same filing', 'E3', '这个结论', or '整理成 memo'. "
                f"Session context:\n{context}"
            )
        return prompt

    def _model_kwargs(self, config: ModelAPIConfig, temperature: float | None = None) -> JsonDict:
        kwargs: JsonDict = {
            "model": config.model,
            "api_key": config.api_key,
            "temperature": config.temperature if temperature is None else temperature,
            "request_timeout": 60,
            "max_retries": 1,
        }
        if config.base_url:
            kwargs["base_url"] = config.base_url
        return kwargs

    def _is_configured(self, config: ModelAPIConfig) -> bool:
        return bool(config.model and config.api_key)
