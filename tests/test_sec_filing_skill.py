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


def test_sec_filing_skill_returns_structured_mock_result():
    result = SecFilingAnalysisSkill(FakeSECClient()).run({"ticker": "aapl", "filing_type": "10-k"})

    assert result.data["ticker"] == "AAPL"
    assert result.data["filing_type"] == "10-K"
    assert result.data["status"] == "metadata_retrieved"
    assert result.evidence
