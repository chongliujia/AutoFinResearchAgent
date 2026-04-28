from autofin.config import ModelAPIConfig, ModelConfigStore
from autofin.intent_router import DeterministicIntentRouter, LLMIntentRouter, RoutedIntent
from autofin.policy import PolicyEngine


class FailingLLMIntentRouter(LLMIntentRouter):
    def _route_with_langchain(self, message, config):
        raise RuntimeError("model unavailable")


def test_routed_intent_normalizes_missing_ticker_for_sec_research():
    routed = RoutedIntent(intent="research_sec_filing", confidence=0.8, filing_type="10 q").normalized()

    assert routed["intent"] == "research_sec_filing"
    assert routed["filing_type"] == "10-Q"
    assert routed["missing_fields"] == ["ticker"]


def test_routed_intent_accepts_provider_string_lists():
    routed = RoutedIntent(
        intent="research_sec_filing",
        ticker="aapl",
        filing_type="10-K",
        focus="risk factors, cash flow",
    ).normalized()

    assert routed["ticker"] == "AAPL"
    assert routed["focus"] == ["risk factors", "cash flow"]


def test_deterministic_router_classifies_sec_research():
    routed = DeterministicIntentRouter().route("帮我分析 MSFT 最近的 10-Q，重点看风险因素和现金流")

    assert routed["intent"] == "research_sec_filing"
    assert routed["ticker"] == "MSFT"
    assert routed["filing_type"] == "10-Q"
    assert routed["focus"] == ["risk factors", "cash flow"]


def test_deterministic_router_classifies_settings_request():
    routed = DeterministicIntentRouter().route("我要配置 DeepSeek API key")

    assert routed["intent"] == "configure_settings"
    assert routed["assistant_reply"]


def test_policy_engine_requires_explicit_run_for_research():
    routed = DeterministicIntentRouter().route("Analyze AAPL 10-K cash flow")
    decision = PolicyEngine().decide(routed)

    assert decision["action"] == "show_run_research_card"
    assert decision["requires_confirmation"] is True


def test_policy_engine_asks_for_missing_ticker():
    routed = DeterministicIntentRouter().route("帮我分析最近的 10-K")
    decision = PolicyEngine().decide(routed)

    assert decision["action"] == "ask_clarification"
    assert decision["missing_fields"] == ["ticker"]


def test_llm_router_does_not_fallback_when_configured_model_fails():
    router = FailingLLMIntentRouter(ModelConfigStore(ModelAPIConfig(model="test-model", api_key="sk-test")))

    routed = router.route("帮我分析 AAPL 最近的 10-K")

    assert routed["intent"] == "intent_routing_failed"
    assert routed["router"] == "langchain_error"
    assert "router_error" in routed


def test_llm_router_requires_model_config_instead_of_deterministic_fallback():
    router = LLMIntentRouter(ModelConfigStore(ModelAPIConfig()))

    routed = router.route("帮我分析 AAPL 最近的 10-K")

    assert routed["intent"] == "configure_settings"
    assert routed["router"] == "unconfigured"
