from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel, Field

from autofin.config import JsonDict, ModelAPIConfig, ModelConfigStore


class ResearchIntent(BaseModel):
    ticker: str | None = Field(default=None, description="Stock ticker symbol, e.g. AAPL.")
    filing_type: str = Field(default="10-K", description="SEC filing type, usually 10-K or 10-Q.")
    objective: str = Field(description="The user's research objective.")
    focus: list[str] = Field(default_factory=list, description="Research focus areas.")

    def normalized(self) -> JsonDict:
        ticker = self.ticker.upper().strip() if self.ticker else None
        filing_type = self.filing_type.upper().replace(" ", "-")
        if filing_type not in {"10-K", "10-Q"}:
            filing_type = "10-K"
        return {
            "ticker": ticker,
            "filing_type": filing_type,
            "objective": self.objective.strip() or "Analyze SEC filing",
            "focus": list(self.focus),
        }


class IntentParser(Protocol):
    def parse(self, message: str) -> JsonDict:
        ...


@dataclass
class DeterministicIntentParser:
    def parse(self, message: str) -> JsonDict:
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
            ticker=ticker,
            filing_type=filing_type,
            objective=message.strip() or "Analyze SEC filing",
            focus=focus,
        ).normalized()


@dataclass
class LangChainIntentParser:
    model_config_store: ModelConfigStore
    fallback: IntentParser = field(default_factory=DeterministicIntentParser)

    def parse(self, message: str) -> JsonDict:
        config = self.model_config_store.get()
        if not self._is_configured(config):
            parsed = self.fallback.parse(message)
            parsed["parser"] = "deterministic"
            return parsed

        try:
            intent = self._parse_with_langchain(message, config)
            parsed = intent.normalized()
            parsed["parser"] = "langchain"
            return parsed
        except Exception as exc:
            parsed = self.fallback.parse(message)
            parsed["parser"] = "deterministic_fallback"
            parsed["parser_error"] = str(exc)
            return parsed

    def _parse_with_langchain(self, message: str, config: ModelAPIConfig) -> ResearchIntent:
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
                        "Only return a ticker when the user clearly names one. "
                        "Use filing_type 10-K or 10-Q when mentioned; otherwise default to 10-K."
                    )
                ),
                HumanMessage(content=message),
            ]
        )
        if isinstance(result, ResearchIntent):
            return result
        return ResearchIntent.model_validate(result)

    def _is_configured(self, config: ModelAPIConfig) -> bool:
        return bool(config.model and config.api_key)
