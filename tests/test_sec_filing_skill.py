from autofin.skills import SecFilingAnalysisSkill


def test_sec_filing_skill_returns_structured_mock_result():
    result = SecFilingAnalysisSkill().run({"ticker": "aapl", "filing_type": "10-k"})

    assert result.data["ticker"] == "AAPL"
    assert result.data["filing_type"] == "10-K"
    assert result.evidence
