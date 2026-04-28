from __future__ import annotations

from typing import Any, Dict

from autofin.data.sec_client import SECClient
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

    def __init__(self, client: SECClient | None = None) -> None:
        self.client = client or SECClient()

    def run(self, inputs: Dict[str, Any]) -> SkillResult:
        ticker = str(inputs.get("ticker", "")).upper()
        filing_type = str(inputs.get("filing_type", "10-K")).upper()
        if not ticker:
            raise ValueError("ticker is required")

        filing = self.client.latest_filing(ticker, filing_type)
        return SkillResult(
            data={
                "ticker": filing.ticker,
                "company_name": filing.company_name,
                "cik": filing.cik,
                "filing_type": filing.filing_type,
                "filing_date": filing.filing_date,
                "report_date": filing.report_date,
                "accession_number": filing.accession_number,
                "primary_document": filing.primary_document,
                "document_url": filing.document_url,
                "summary": (
                    f"Retrieved {filing.company_name} {filing.filing_type} filed on "
                    f"{filing.filing_date}. Section extraction and financial analysis "
                    "will be added in the next iteration."
                ),
                "status": "metadata_retrieved",
            },
            evidence=[
                {
                    "source": "sec.gov",
                    "kind": "filing_document",
                    "url": filing.document_url,
                    "accession_number": filing.accession_number,
                    "filing_date": filing.filing_date,
                },
                {
                    "source": "sec.gov",
                    "kind": "filing_index",
                    "url": filing.index_url,
                }
            ],
            warnings=["This skill currently retrieves filing metadata and document links only."],
        )
