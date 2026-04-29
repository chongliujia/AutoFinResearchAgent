from autofin.skills import SecFilingAnalysisSkill


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


def test_sec_filing_skill_returns_structured_mock_result():
    result = SecFilingAnalysisSkill(FakeSECClient()).run({"ticker": "aapl", "filing_type": "10-k"})

    assert result.data["ticker"] == "AAPL"
    assert result.data["filing_type"] == "10-K"
    assert result.data["status"] == "analysis_completed"
    assert "analysis" in result.data
    assert result.data["analysis"]["sections"]["risk_factors"]["highlights"]
    assert any(item["kind"] == "filing_excerpt" for item in result.evidence)
    assert result.evidence
