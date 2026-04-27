from time import sleep

from fastapi.testclient import TestClient

from autofin.web.app import app


client = TestClient(app)


def test_web_app_health_and_skills():
    health = client.get("/api/health")
    skills = client.get("/api/skills")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert skills.status_code == 200
    assert skills.json()["skills"][0]["name"] == "sec_filing_analysis"


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
