from autofin.skills import SecFilingAnalysisSkill
from autofin.skills.sec_filing import MarkdownMemoArtifactWriter


class FakeSECClient:
    def latest_filing(self, ticker, filing_type):
        from autofin.data.sec_client import SECFiling

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
            <p>Apple designs, manufactures and markets smartphones, personal computers, tablets,
            wearables and accessories, and sells a variety of related services. Revenue depends on
            product demand, platform adoption, customers, and the Company's ecosystem.</p>
            <h1>Item 1A. Risk Factors</h1>
            <p>The Company faces substantial competition and risks that could adversely affect
            revenue, margins, operating results, cash flow, and customer demand. These risks may
            include supply constraints, cybersecurity incidents, regulation, and macroeconomic conditions.</p>
            <h1>Item 7. Management's Discussion and Analysis</h1>
            <p>Management discusses revenue, gross margin, operating expenses, net income,
            liquidity, and cash flow. Operating income and cash flow trends are used to evaluate
            performance and capital allocation.</p>
            <h1>Item 8. Financial Statements</h1>
            <p>The consolidated financial statements include revenue, net income, cash, total assets,
            liabilities, and stockholders' equity in the balance sheet and statements of cash flows.</p>
          </body>
        </html>
        """


def test_sec_filing_skill_returns_structured_mock_result(tmp_path):
    result = SecFilingAnalysisSkill(
        FakeSECClient(),
        artifact_writer=MarkdownMemoArtifactWriter(tmp_path),
    ).run({"ticker": "aapl", "filing_type": "10-k"})

    assert result.data["ticker"] == "AAPL"
    assert result.data["filing_type"] == "10-K"
    assert result.data["status"] == "analysis_completed"
    assert "analysis" in result.data
    assert result.data["analysis"]["report"]["title"] == "AAPL 10-K Evidence-Grounded Memo"
    assert result.data["analysis"]["report"]["memo_style"] == "extractive"
    assert result.data["analysis"]["memo_metadata"]["memo_status"] == "extractive_fallback"
    assert result.data["analysis"]["citation_validation"]["status"] == "passed"
    assert result.data["analysis"]["artifacts"][0]["kind"] == "markdown_memo"
    assert "Evidence References" in (tmp_path / "aapl_10-k_0000320193-25-000079_memo.md").read_text()
    assert result.data["analysis"]["report"]["key_observations"]
    assert result.data["analysis"]["sections"]["risk_factors"]["highlights"]
    assert result.evidence[2]["citation_id"] == "E1"
    assert any(item["kind"] == "filing_excerpt" for item in result.evidence)
    assert result.evidence


def test_sec_filing_skill_accepts_model_backed_memo_synthesizer(tmp_path):
    class FakeMemoSynthesizer:
        def synthesize(self, filing, analysis, evidence):
            return {
                "report": {
                    "title": "Model memo",
                    "memo_style": "llm_evidence_grounded",
                    "executive_summary": "Evidence-grounded memo.",
                    "key_observations": [
                        {"title": "Business", "summary": "Business summary", "citations": ["E1"]}
                    ],
                    "risk_watchlist": [
                        {"risk": "Competition", "why_it_matters": "Margin pressure", "citations": ["E2"]}
                    ],
                    "limitations": ["Evidence only"],
                },
                "metadata": {"memo_synthesizer": "fake", "memo_status": "model_synthesized"},
            }

    result = SecFilingAnalysisSkill(
        FakeSECClient(),
        memo_synthesizer=FakeMemoSynthesizer(),
        artifact_writer=MarkdownMemoArtifactWriter(tmp_path),
    ).run({"ticker": "aapl", "filing_type": "10-k"})

    assert result.data["analysis"]["report"]["memo_style"] == "llm_evidence_grounded"
    assert result.data["analysis"]["report"]["key_observations"][0]["citations"] == ["E1"]
    assert result.data["analysis"]["memo_metadata"]["memo_status"] == "model_synthesized"
    assert result.data["analysis"]["citation_validation"]["status"] == "passed"
    assert result.data["analysis"]["extractive_report"]["memo_style"] == "extractive"


def test_sec_filing_skill_marks_invalid_model_citations(tmp_path):
    class BadMemoSynthesizer:
        def synthesize(self, filing, analysis, evidence):
            return {
                "report": {
                    "title": "Bad model memo",
                    "memo_style": "llm_evidence_grounded",
                    "executive_summary": "Uses a bad citation.",
                    "key_observations": [
                        {"title": "Business", "summary": "Business summary", "citations": ["E999"]}
                    ],
                    "risk_watchlist": [
                        {"risk": "Competition", "why_it_matters": "Margin pressure", "citations": []}
                    ],
                    "limitations": ["Evidence only"],
                },
                "metadata": {"memo_synthesizer": "fake", "memo_status": "model_synthesized"},
            }

    result = SecFilingAnalysisSkill(
        FakeSECClient(),
        memo_synthesizer=BadMemoSynthesizer(),
        artifact_writer=MarkdownMemoArtifactWriter(tmp_path),
    ).run({"ticker": "aapl", "filing_type": "10-k"})

    validation = result.data["analysis"]["citation_validation"]
    assert validation["status"] == "warning"
    assert validation["invalid_citations"] == ["E999"]
    assert validation["missing_citation_items"] == ["risk_watchlist[1]"]
    assert result.data["analysis"]["memo_metadata"]["memo_status"] == "model_synthesized_with_warnings"
    assert any("citation validation" in warning for warning in result.warnings)
