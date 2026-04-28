from autofin.config import ModelAPIConfig, ModelConfigStore
from autofin.intent import DeterministicIntentParser, LangChainIntentParser


class FakeParser:
    def parse(self, message: str):
        return {
            "ticker": "TSLA",
            "filing_type": "10-Q",
            "objective": message,
            "focus": ["revenue"],
            "parser": "fake",
        }


class FailingLangChainParser(LangChainIntentParser):
    def _parse_with_langchain(self, message, config):
        raise RuntimeError("model unavailable")


def test_deterministic_parser_extracts_research_intent():
    parsed = DeterministicIntentParser().parse("帮我分析 MSFT 最近的 10-Q，重点看风险因素和现金流")

    assert parsed["ticker"] == "MSFT"
    assert parsed["filing_type"] == "10-Q"
    assert parsed["focus"] == ["risk factors", "cash flow"]


def test_langchain_parser_uses_deterministic_fallback_when_unconfigured():
    parser = LangChainIntentParser(ModelConfigStore(ModelAPIConfig()))

    parsed = parser.parse("Analyze AAPL 10-K cash flow")

    assert parsed["ticker"] == "AAPL"
    assert parsed["parser"] == "deterministic"


def test_langchain_parser_falls_back_when_model_call_fails():
    parser = FailingLangChainParser(
        ModelConfigStore(ModelAPIConfig(model="test-model", api_key="sk-test")),
        fallback=FakeParser(),
    )

    parsed = parser.parse("any message")

    assert parsed["ticker"] == "TSLA"
    assert parsed["parser"] == "deterministic_fallback"
    assert parsed["parser_error"]
