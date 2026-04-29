from autofin.data.sec_client import SECFiling
from autofin.runtime import ResearchOrchestrator, SkillRegistry, TraceLogger
from autofin.schemas import ResearchTask
from autofin.skills import SecFilingAnalysisSkill


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
            <p>Apple has a platform business with revenue from products, services,
            customers, subscriptions, and commercial channels.</p>
            <h1>Item 1A. Risk Factors</h1>
            <p>Risks may adversely affect revenue, margins, cash flow, customers,
            competition, cybersecurity, regulation, and operating results.</p>
            <h1>Item 7. Management's Discussion and Analysis</h1>
            <p>Management discusses revenue, operating income, net income, expenses,
            liquidity, margin, and cash flow trends.</p>
            <h1>Item 8. Financial Statements</h1>
            <p>The financial statements include revenue, net income, cash, total assets,
            balance sheet items, and stockholders' equity.</p>
          </body>
        </html>
        """


def test_orchestrator_runs_langgraph_skill_flow(tmp_path):
    registry = SkillRegistry([SecFilingAnalysisSkill(FakeSECClient())])
    orchestrator = ResearchOrchestrator(
        registry,
        trace_logger=TraceLogger(tmp_path / "traces.jsonl"),
    )
    task = ResearchTask(
        objective="Analyze AAPL 10-K",
        inputs={"ticker": "AAPL", "filing_type": "10-K"},
    )

    state = orchestrator.run(task)

    assert state["selected_skill"] == "sec_filing_analysis"
    assert state["permission_status"] == "approved"
    assert state["result"]["data"]["ticker"] == "AAPL"
    assert (tmp_path / "traces.jsonl").exists()
