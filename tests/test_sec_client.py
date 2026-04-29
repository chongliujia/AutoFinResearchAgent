from autofin.data.sec_client import SECClient


def test_sec_client_resolves_latest_filing_metadata():
    responses = {
        SECClient.ticker_map_url: {
            "0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}
        },
        SECClient.submissions_url.format(cik="0000320193"): {
            "name": "Apple Inc.",
            "filings": {
                "recent": {
                    "accessionNumber": ["0000320193-25-000079", "0000320193-25-000010"],
                    "filingDate": ["2025-10-31", "2025-08-01"],
                    "reportDate": ["2025-09-27", "2025-06-28"],
                    "form": ["10-K", "10-Q"],
                    "primaryDocument": ["aapl-20250927.htm", "aapl-20250628.htm"],
                }
            },
        },
    }
    client = SECClient(fetch_json=lambda url: responses[url])

    filing = client.latest_filing("aapl", "10-K")

    assert filing.ticker == "AAPL"
    assert filing.cik == "0000320193"
    assert filing.company_name == "Apple Inc."
    assert filing.accession_number == "0000320193-25-000079"
    assert filing.document_url.endswith("/320193/000032019325000079/aapl-20250927.htm")


def test_sec_client_fetches_filing_document_with_injected_fetcher():
    client = SECClient(fetch_json=lambda url: {}, fetch_text=lambda url: "<html>filing</html>")

    class Filing:
        document_url = "https://www.sec.gov/Archives/test.htm"

    assert client.fetch_filing_document(Filing()) == "<html>filing</html>"
