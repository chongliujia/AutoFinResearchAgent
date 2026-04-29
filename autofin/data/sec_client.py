from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, Iterable, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


JsonDict = Dict[str, Any]
JsonFetcher = Callable[[str], JsonDict]
TextFetcher = Callable[[str], str]


@dataclass(frozen=True)
class SECFiling:
    ticker: str
    cik: str
    company_name: str
    filing_type: str
    accession_number: str
    filing_date: str
    report_date: str
    primary_document: str
    document_url: str
    index_url: str

    def to_dict(self) -> JsonDict:
        return asdict(self)


class SECClient:
    ticker_map_url = "https://www.sec.gov/files/company_tickers.json"
    submissions_url = "https://data.sec.gov/submissions/CIK{cik}.json"

    def __init__(
        self,
        user_agent: Optional[str] = None,
        fetch_json: Optional[JsonFetcher] = None,
        fetch_text: Optional[TextFetcher] = None,
    ) -> None:
        self.user_agent = (
            user_agent
            or os.getenv("AUTOFIN_SEC_USER_AGENT")
            or "AutoFinResearchAgent contact@example.com"
        )
        self._fetch_json = fetch_json or self._default_fetch_json
        self._fetch_text = fetch_text or self._default_fetch_text
        self._ticker_map: Optional[dict[str, JsonDict]] = None

    def latest_filing(self, ticker: str, filing_type: str = "10-K") -> SECFiling:
        ticker = ticker.upper().strip()
        filing_type = filing_type.upper().strip()
        company = self.lookup_company(ticker)
        cik = self._format_cik(company["cik_str"])
        submissions = self._fetch_json(self.submissions_url.format(cik=cik))
        recent = submissions.get("filings", {}).get("recent", {})
        row = self._find_recent_filing_row(recent, filing_type)
        accession_number = str(row["accessionNumber"])
        primary_document = str(row["primaryDocument"])
        accession_path = accession_number.replace("-", "")
        cik_path = str(int(cik))

        return SECFiling(
            ticker=ticker,
            cik=cik,
            company_name=str(submissions.get("name") or company.get("title") or ticker),
            filing_type=str(row["form"]),
            accession_number=accession_number,
            filing_date=str(row.get("filingDate", "")),
            report_date=str(row.get("reportDate", "")),
            primary_document=primary_document,
            document_url=(
                "https://www.sec.gov/Archives/edgar/data/"
                f"{cik_path}/{accession_path}/{primary_document}"
            ),
            index_url=(
                "https://www.sec.gov/Archives/edgar/data/"
                f"{cik_path}/{accession_path}/"
            ),
        )

    def lookup_company(self, ticker: str) -> JsonDict:
        ticker = ticker.upper().strip()
        ticker_map = self._get_ticker_map()
        try:
            return ticker_map[ticker]
        except KeyError as exc:
            raise LookupError(f"SEC ticker not found: {ticker}") from exc

    def fetch_filing_document(self, filing: SECFiling) -> str:
        return self._fetch_text(filing.document_url)

    def _get_ticker_map(self) -> dict[str, JsonDict]:
        if self._ticker_map is None:
            raw = self._fetch_json(self.ticker_map_url)
            self._ticker_map = {
                str(item["ticker"]).upper(): item for item in self._iter_company_ticker_items(raw)
            }
        return self._ticker_map

    def _iter_company_ticker_items(self, raw: JsonDict) -> Iterable[JsonDict]:
        if isinstance(raw, dict):
            return raw.values()
        if isinstance(raw, list):
            return raw
        raise ValueError("Unexpected SEC company ticker response")

    def _find_recent_filing_row(self, recent: JsonDict, filing_type: str) -> JsonDict:
        forms = list(recent.get("form", []))
        for index, form in enumerate(forms):
            if str(form).upper() == filing_type:
                return {key: values[index] for key, values in recent.items() if index < len(values)}
        raise LookupError(f"No recent SEC filing found for form type: {filing_type}")

    def _default_fetch_json(self, url: str) -> JsonDict:
        request = Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            raise RuntimeError(f"SEC request failed with HTTP {exc.code}: {url}") from exc
        except URLError as exc:
            raise RuntimeError(f"SEC request failed: {url}") from exc

    def _default_fetch_text(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml,text/plain",
                "User-Agent": self.user_agent,
            },
        )
        try:
            with urlopen(request, timeout=30) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except HTTPError as exc:
            raise RuntimeError(f"SEC document request failed with HTTP {exc.code}: {url}") from exc
        except URLError as exc:
            raise RuntimeError(f"SEC document request failed: {url}") from exc

    def _format_cik(self, cik: Any) -> str:
        return str(int(cik)).zfill(10)
