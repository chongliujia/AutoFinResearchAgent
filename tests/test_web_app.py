from time import sleep

from fastapi.testclient import TestClient

import autofin.web.app as web_app
from autofin.data.sec_client import SECFiling
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


web_app.store = TaskStore(skills=[SecFilingAnalysisSkill(FakeSECClient())])
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
    assert task["event_count"] >= 5


def test_web_app_creates_task_from_chat_message():
    response = client.post(
        "/api/chat",
        json={"message": "帮我分析 MSFT 最近的 10-Q，重点看风险因素和现金流"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "task_created"
    assert payload["parsed"]["ticker"] == "MSFT"
    assert payload["parsed"]["filing_type"] == "10-Q"
    assert payload["task"]["messages"][0]["role"] == "user"


def test_web_app_chat_requests_ticker_when_missing():
    response = client.post(
        "/api/chat",
        json={"message": "帮我分析最近的 10-K，重点看现金流"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "needs_clarification"
    assert payload["task"] is None
    assert payload["assistant_message"]["metadata"]["needs"] == ["ticker"]


def test_task_store_accepts_injected_intent_parser():
    class FakeIntentParser:
        def parse(self, message: str):
            return {
                "ticker": "TSLA",
                "filing_type": "10-Q",
                "objective": message,
                "focus": ["revenue"],
                "parser": "fake",
            }

    record, result = TaskStore(intent_parser=FakeIntentParser()).create_chat_task("Analyze Tesla")

    assert record is not None
    assert record.inputs == {"ticker": "TSLA", "filing_type": "10-Q"}
    assert result["parsed"]["parser"] == "fake"
