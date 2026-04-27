from __future__ import annotations

from typing import Any, Dict

from autofin.schemas import PermissionSet, SkillResult
from autofin.skills.base import Skill


class SecFilingAnalysisSkill(Skill):
    name = "sec_filing_analysis"
    description = "Analyze SEC 10-K or 10-Q filings and return a summary with evidence."
    permissions = PermissionSet(
        network=["sec.gov"],
        filesystem=["write_temp"],
        secrets=[],
    )

    def run(self, inputs: Dict[str, Any]) -> SkillResult:
        ticker = str(inputs.get("ticker", "")).upper()
        filing_type = str(inputs.get("filing_type", "10-K")).upper()
        if not ticker:
            raise ValueError("ticker is required")

        return SkillResult(
            data={
                "ticker": ticker,
                "filing_type": filing_type,
                "summary": (
                    f"Mock {filing_type} analysis for {ticker}. "
                    "The real implementation will fetch SEC filings, extract sections, "
                    "and produce risk, liquidity, and operating trend analysis."
                ),
                "status": "mocked",
            },
            evidence=[
                {
                    "source": "sec.gov",
                    "kind": "planned_integration",
                    "note": "SEC retrieval is intentionally mocked in the MVP skeleton.",
                }
            ],
            warnings=["This skill currently returns mock data."],
        )
