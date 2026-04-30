from time import sleep

from fastapi.testclient import TestClient

import autofin.web.app as web_app
from autofin.data.sec_client import SECFiling
from autofin.session import SessionStore
from autofin.skills import SecFilingAnalysisSkill
from autofin.web.task_store import TaskStore


class FakeSECClient:
    def latest_filing(self, ticker, filing_type):
        return SECFiling(
            ticker=ticker.upper(),
            cik="0000320193",
            company_name="Apple Inc.",
            filing_type=filing_type.upper(),
            accession_number="0000320193-25-000079",
            filing_date="2025-10-31",
            report_date="2025-09-27",
            primary_document="aapl-20250927.htm",
            document_url="https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm",
            index_url="https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/",
        )

    def fetch_filing_document(self, filing):
        return """
        <html>
          <body>
            <h1>Item 1. Business</h1>
            <p>Apple sells products and services through a platform business with customers,
            subscriptions, commercial channels, and government channels. Revenue depends on
            product demand and customer engagement.</p>
            <h1>Item 1A. Risk Factors</h1>
            <p>The company faces risks that may adversely affect revenue, margins, cash flow,
            customers, competition, cybersecurity, regulation, and operations.</p>
            <h1>Item 7. Management's Discussion and Analysis</h1>
            <p>Management reviews revenue, operating income, net income, expenses, margin,
            liquidity, and cash flow trends for the fiscal period.</p>
            <h1>Item 8. Financial Statements</h1>
            <p>Financial statements include revenue, net income, cash, total assets, balance sheet
            items, and stockholders' equity.</p>
          </body>
        </html>
        """


web_app.store = TaskStore(
    skills=[SecFilingAnalysisSkill(FakeSECClient())],
    session_store=SessionStore(persist=False),
    persist_tasks=False,
)
web_app.model_config_store.persist = False
client = TestClient(web_app.app)


def test_web_app_health_and_skills():
    health = client.get("/api/health")
    skills = client.get("/api/skills")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert skills.status_code == 200
    assert skills.json()["skills"][0]["name"] == "sec_filing_analysis"


def test_web_app_model_settings_redact_api_key():
    response = client.post(
        "/api/settings/model",
        json={
            "provider": "openai-compatible",
            "model": "test-model",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test-secret",
            "temperature": 0.1,
        },
    )

    assert response.status_code == 200
    payload = response.json()["model_api"]
    assert payload["model"] == "test-model"
    assert payload["api_key_configured"] is True
    assert payload["api_key_preview"] == "sk-t...cret"
    assert "sk-test-secret" not in response.text


def test_web_app_creates_research_task():
    response = client.post(
        "/api/tasks",
        json={"ticker": "AAPL", "filing_type": "10-K", "objective": "Analyze SEC filing"},
    )

    assert response.status_code == 200
    task_id = response.json()["id"]

    task = None
    for _ in range(10):
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] == "completed":
            break
        sleep(0.05)

    assert task["status"] == "completed"
    assert task["result"]["result"]["data"]["ticker"] == "AAPL"
    assert task["result"]["result"]["data"]["analysis"]["report"]["key_observations"]
    assert task["event_count"] >= 5


def test_web_app_creates_task_from_chat_message():
    session = client.post("/api/sessions").json()["session"]
    response = client.post(
        "/api/research/run",
        json={"message": "帮我分析 MSFT 最近的 10-Q，重点看风险因素和现金流", "session_id": session["id"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "task_created"
    assert payload["routed_intent"]["ticker"] == "MSFT"
    assert payload["routed_intent"]["filing_type"] == "10-Q"
    assert payload["session_id"] == session["id"]
    assert payload["task"]["session_id"] == session["id"]
    assert payload["task"]["messages"][0]["role"] == "user"

    task_id = payload["task"]["id"]
    task = None
    for _ in range(10):
        task = client.get(f"/api/tasks/{task_id}").json()
        if task["status"] == "completed":
            break
        sleep(0.05)

    assert task["status"] == "completed"
    updated_session = client.get(f"/api/sessions/{session['id']}").json()["session"]
    assert updated_session["task_summaries"][0]["task_id"] == task_id
    assert updated_session["task_summaries"][0]["ticker"] == "MSFT"


def test_web_app_chat_routes_general_conversation():
    session = client.post("/api/sessions").json()["session"]
    response = client.post(
        "/api/chat",
        json={"message": "你好，你能做什么？", "session_id": session["id"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "routed"
    assert payload["task"] is None
    assert payload["assistant_message"]["role"] == "assistant"
    assert payload["session_id"] == session["id"]
    assert payload["routed_intent"]["intent"] in {"general_chat", "explain_app"}
    assert payload["policy_decision"]["action"] == "stream_chat"


def test_web_app_chat_returns_run_research_card():
    session = client.post("/api/sessions").json()["session"]
    response = client.post(
        "/api/chat",
        json={"message": "帮我分析 MSFT 最近的 10-Q，重点看风险因素和现金流", "session_id": session["id"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "routed"
    assert payload["task"] is None
    assert payload["routed_intent"]["intent"] == "research_sec_filing"
    assert payload["policy_decision"]["action"] == "show_run_research_card"
    assert payload["action_card"]["ticker"] == "MSFT"
    stored = client.get(f"/api/sessions/{session['id']}").json()["session"]
    assert stored["messages"][0]["role"] == "user"


def test_web_app_lists_and_gets_sessions():
    created = client.post("/api/sessions").json()["session"]
    listed = client.get("/api/sessions").json()["sessions"]
    fetched = client.get(f"/api/sessions/{created['id']}").json()["session"]

    assert any(session["id"] == created["id"] for session in listed)
    assert fetched["id"] == created["id"]


def test_web_app_deletes_one_session():
    created = client.post("/api/sessions").json()["session"]

    response = client.delete(f"/api/sessions/{created['id']}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted_session_id"] == created["id"]
    assert payload["active_session"]["id"] != created["id"]


def test_web_app_deletes_all_sessions_and_creates_replacement():
    client.post("/api/sessions")
    client.post("/api/sessions")

    response = client.delete("/api/sessions")

    assert response.status_code == 200
    payload = response.json()
    assert payload["deleted_count"] >= 2
    assert len(payload["sessions"]) == 1
    assert payload["active_session"]["id"] == payload["sessions"][0]["id"]


def test_web_app_streams_general_chat_response():
    session = client.post("/api/sessions").json()["session"]
    with client.stream("POST", "/api/chat/stream", json={"message": "你好", "session_id": session["id"]}) as response:
        body = response.read().decode("utf-8")

    assert response.status_code == 200
    assert "event: chat-meta" in body
    assert session["id"] in body
    assert "event: chat-token" in body
    assert "event: chat-done" in body


def test_web_app_chat_requests_ticker_when_missing():
    session = client.post("/api/sessions").json()["session"]
    response = client.post(
        "/api/chat",
        json={"message": "帮我分析最近的 10-K，重点看现金流", "session_id": session["id"]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "routed"
    assert payload["task"] is None
    assert payload["policy_decision"]["action"] == "ask_clarification"
    assert payload["routed_intent"]["missing_fields"] == ["ticker"]


def test_task_store_accepts_injected_intent_parser():
    class FakeIntentParser:
        def parse(self, message: str):
            return {
                "intent_type": "research_task",
                "ticker": "TSLA",
                "filing_type": "10-Q",
                "objective": message,
                "focus": ["revenue"],
                "reply": "",
                "parser": "fake",
            }

    record, result = TaskStore(intent_parser=FakeIntentParser(), persist_tasks=False).create_chat_task("Analyze Tesla")

    assert record is not None
    assert record.inputs == {"ticker": "TSLA", "filing_type": "10-Q"}
    assert result["parsed"]["parser"] == "fake"


def test_task_store_accepts_injected_chat_responder():
    class ConversationParser:
        def parse(self, message: str):
            return {
                "intent_type": "conversation",
                "ticker": None,
                "filing_type": "10-K",
                "objective": message,
                "focus": [],
                "reply": "",
                "parser": "fake",
            }

    class FakeChatResponder:
        def reply(self, message: str):
            return "model-backed reply", {"responder": "fake_model"}

        def stream_reply(self, message: str):
            yield "model-backed"
            yield " reply"

    record, result = TaskStore(
        intent_parser=ConversationParser(),
        chat_responder=FakeChatResponder(),
        persist_tasks=False,
    ).create_chat_task("hello")

    assert record is None
    assert result["assistant_message"]["content"] == "model-backed reply"
    assert result["assistant_message"]["metadata"]["responder"] == "fake_model"


def test_task_store_persists_completed_task_results(tmp_path):
    task_root = tmp_path / "tasks"
    store = TaskStore(
        skills=[SecFilingAnalysisSkill(FakeSECClient())],
        session_store=SessionStore(persist=False),
        task_root=task_root,
    )
    record = store.create_task(
        objective="Analyze PLTR 10-K",
        skill_name="sec_filing_analysis",
        inputs={"ticker": "PLTR", "filing_type": "10-K"},
    )

    store.run_task(record.id)

    reloaded = TaskStore(
        skills=[SecFilingAnalysisSkill(FakeSECClient())],
        session_store=SessionStore(persist=False),
        task_root=task_root,
    )
    task = reloaded.get_task(record.id).public_view()

    assert task["status"] == "completed"
    assert task["result"]["result"]["data"]["ticker"] == "PLTR"
    assert task["event_count"] >= 5
