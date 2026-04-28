from autofin.config import ModelAPIConfig, ModelConfigStore
from autofin.intent import DeterministicChatResponder, DeterministicIntentParser, LangChainIntentParser, ResearchIntent


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

    assert parsed["intent_type"] == "research_task"
    assert parsed["ticker"] == "MSFT"
    assert parsed["filing_type"] == "10-Q"
    assert parsed["focus"] == ["risk factors", "cash flow"]


def test_deterministic_parser_allows_general_conversation():
    parsed = DeterministicIntentParser().parse("你好，你能做什么？")

    assert parsed["intent_type"] == "conversation"
    assert parsed["ticker"] is None
    assert parsed["reply"]


def test_research_intent_normalizes_null_filing_type():
    parsed = ResearchIntent(
        intent_type="conversation",
        ticker=None,
        filing_type=None,
        objective="hello",
        focus=[],
        reply="hi",
    ).normalized()

    assert parsed["filing_type"] == "10-K"


def test_deterministic_chat_responder_replies_to_general_chat():
    reply, metadata = DeterministicChatResponder().reply("你好")

    assert reply
    assert metadata["responder"] == "deterministic"


def test_langchain_parser_uses_deterministic_fallback_when_unconfigured():
    parser = LangChainIntentParser(ModelConfigStore(ModelAPIConfig()))

    parsed = parser.parse("Analyze AAPL 10-K cash flow")

    assert parsed["ticker"] == "AAPL"
    assert parsed["parser"] == "deterministic"


def test_langchain_parser_prechecks_general_conversation_without_model_call():
    parser = FailingLangChainParser(
        ModelConfigStore(ModelAPIConfig(model="test-model", api_key="sk-test")),
        fallback=DeterministicIntentParser(),
    )

    parsed = parser.parse("你好，你能做什么？")

    assert parsed["intent_type"] == "conversation"
    assert parsed["parser"] == "deterministic_precheck"


def test_langchain_parser_falls_back_when_model_call_fails():
    parser = FailingLangChainParser(
        ModelConfigStore(ModelAPIConfig(model="test-model", api_key="sk-test")),
        fallback=FakeParser(),
    )

    parsed = parser.parse("any message")

    assert parsed["ticker"] == "TSLA"
    assert parsed["parser"] == "deterministic_fallback"
    assert parsed["parser_error"]
