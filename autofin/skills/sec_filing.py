from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Dict, Iterable, List

from autofin.data.sec_client import SECClient
from autofin.schemas import PermissionSet, SkillResult
from autofin.skills.base import Skill


SECTION_PATTERNS = {
    "business": [r"item\s+1[\.\s]+business"],
    "risk_factors": [r"item\s+1a[\.\s]+risk\s+factors"],
    "mda": [
        r"item\s+7[\.\s]+management",
        r"item\s+2[\.\s]+management",
        r"management.?s\s+discussion\s+and\s+analysis",
    ],
    "financial_statements": [
        r"item\s+8[\.\s]+financial\s+statements",
        r"item\s+1[\.\s]+financial\s+statements",
    ],
}

SECTION_KEYWORDS = {
    "business": [
        "business",
        "platform",
        "product",
        "customers",
        "revenue",
        "commercial",
        "government",
        "subscription",
    ],
    "risk_factors": [
        "risk",
        "may",
        "could",
        "adverse",
        "depend",
        "cybersecurity",
        "regulation",
        "competition",
    ],
    "mda": [
        "revenue",
        "operating income",
        "net income",
        "cash flow",
        "expenses",
        "margin",
        "liquidity",
    ],
    "financial_statements": [
        "total assets",
        "cash",
        "revenue",
        "net income",
        "stockholders",
        "balance sheet",
    ],
}


class FilingHTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks: List[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "noscript"}:
            self._skip_depth += 1
        if tag.lower() in {"p", "div", "tr", "br", "li", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
        if tag.lower() in {"p", "div", "tr", "li", "h1", "h2", "h3", "h4"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        cleaned = " ".join(data.split())
        if cleaned:
            self._chunks.append(cleaned)

    def text(self) -> str:
        raw = " ".join(self._chunks)
        raw = re.sub(r"[ \t\r\f\v]+", " ", raw)
        raw = re.sub(r" *\n+ *", "\n", raw)
        raw = re.sub(r"\n{2,}", "\n", raw)
        raw = re.sub(r"\s*(Item\s+\d+[A-Z]?\.)", r"\n\1", raw, flags=re.IGNORECASE)
        return raw.strip()


@dataclass(frozen=True)
class FilingExcerpt:
    section: str
    text: str
    score: int


class FilingDocumentAnalyzer:
    def analyze(self, html: str, filing_type: str) -> Dict[str, Any]:
        text = self._html_to_text(html)
        paragraphs = self._paragraphs(text)
        sections = self._extract_sections(text, filing_type)
        section_summaries: Dict[str, Dict[str, Any]] = {}
        excerpts: List[FilingExcerpt] = []

        for section, keywords in SECTION_KEYWORDS.items():
            source_text = sections.get(section) or text
            candidates = self._rank_paragraphs(self._paragraphs(source_text), keywords)
            if not candidates:
                candidates = self._rank_paragraphs(paragraphs, keywords)
            selected = [
                FilingExcerpt(section=section, text=item.text, score=item.score)
                for item in candidates[:3]
            ]
            excerpts.extend(selected)
            section_summaries[section] = {
                "found_section": bool(sections.get(section)),
                "highlights": [self._sentence_summary(item.text) for item in selected],
            }

        return {
            "status": "analysis_completed",
            "text_stats": {
                "characters": len(text),
                "paragraphs": len(paragraphs),
                "sections_found": sorted([key for key, value in sections.items() if value]),
            },
            "sections": section_summaries,
            "summary": self._overall_summary(section_summaries),
            "excerpts": excerpts[:10],
        }

    def _html_to_text(self, html: str) -> str:
        parser = FilingHTMLTextParser()
        parser.feed(html)
        return parser.text()

    def _paragraphs(self, text: str) -> List[str]:
        parts = re.split(r"(?:\n+|(?<=\.)\s{2,})", text)
        paragraphs = []
        for part in parts:
            cleaned = " ".join(part.split())
            if 80 <= len(cleaned) <= 1600:
                paragraphs.append(cleaned)
        return paragraphs

    def _extract_sections(self, text: str, filing_type: str) -> Dict[str, str]:
        lowered = text.lower()
        starts: list[tuple[str, int]] = []
        for section, patterns in SECTION_PATTERNS.items():
            for pattern in patterns:
                matches = list(re.finditer(pattern, lowered, re.IGNORECASE))
                if matches:
                    starts.append((section, matches[-1].start()))
                    break
        starts.sort(key=lambda item: item[1])
        sections: Dict[str, str] = {}
        for index, (section, start) in enumerate(starts):
            end = starts[index + 1][1] if index + 1 < len(starts) else min(len(text), start + 120_000)
            sections[section] = text[start:end]
        return sections

    def _rank_paragraphs(self, paragraphs: Iterable[str], keywords: list[str]) -> List[FilingExcerpt]:
        ranked: List[FilingExcerpt] = []
        for paragraph in paragraphs:
            lowered = paragraph.lower()
            score = sum(lowered.count(keyword) for keyword in keywords)
            if score:
                ranked.append(FilingExcerpt(section="", text=paragraph, score=score))
        ranked.sort(key=lambda item: (item.score, len(item.text)), reverse=True)
        return ranked

    def _sentence_summary(self, text: str) -> str:
        sentence = re.split(r"(?<=[.!?])\s+", text.strip())[0]
        if len(sentence) > 260:
            return sentence[:257].rstrip() + "..."
        return sentence

    def _overall_summary(self, sections: Dict[str, Dict[str, Any]]) -> str:
        found = [name for name, value in sections.items() if value.get("highlights")]
        if not found:
            return "Downloaded filing text but did not find enough analyzable paragraphs."
        labels = {
            "business": "business",
            "risk_factors": "risk factors",
            "mda": "MD&A",
            "financial_statements": "financial statements",
        }
        joined = ", ".join(labels.get(name, name) for name in found)
        return f"Analyzed filing text and extracted evidence-backed highlights for {joined}."


class SecFilingAnalysisSkill(Skill):
    name = "sec_filing_analysis"
    description = "Analyze SEC 10-K or 10-Q filings and return a summary with evidence."
    permissions = PermissionSet(
        network=["sec.gov"],
        filesystem=["write_temp"],
        secrets=[],
    )

    def __init__(self, client: SECClient | None = None, analyzer: FilingDocumentAnalyzer | None = None) -> None:
        self.client = client or SECClient()
        self.analyzer = analyzer or FilingDocumentAnalyzer()

    def run(self, inputs: Dict[str, Any]) -> SkillResult:
        ticker = str(inputs.get("ticker", "")).upper()
        filing_type = str(inputs.get("filing_type", "10-K")).upper()
        if not ticker:
            raise ValueError("ticker is required")

        filing = self.client.latest_filing(ticker, filing_type)
        html = self.client.fetch_filing_document(filing)
        analysis = self.analyzer.analyze(html, filing.filing_type)
        excerpt_evidence = [
            {
                "source": "sec.gov",
                "kind": "filing_excerpt",
                "section": excerpt.section or "matched_text",
                "note": self.analyzer._sentence_summary(excerpt.text),
                "excerpt": excerpt.text[:700],
                "url": filing.document_url,
            }
            for excerpt in analysis.pop("excerpts")
        ]
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
                "summary": analysis["summary"],
                "analysis": analysis,
                "status": analysis["status"],
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
                },
                *excerpt_evidence,
            ],
            warnings=[
                "Automated filing analysis is extractive and evidence-grounded; it is not investment advice.",
                "LLM narrative synthesis and numeric statement parsing are planned for a later iteration.",
            ],
        )
