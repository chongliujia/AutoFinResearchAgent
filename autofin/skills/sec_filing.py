from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, Iterable, List, Protocol

from autofin.config import ModelAPIConfig, ModelConfigStore
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

SECTION_LABELS = {
    "business": "Business",
    "risk_factors": "Risk Factors",
    "mda": "MD&A",
    "financial_statements": "Financial Statements",
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

        report = self._build_report(section_summaries)

        return {
            "status": "analysis_completed",
            "text_stats": {
                "characters": len(text),
                "paragraphs": len(paragraphs),
                "sections_found": sorted([key for key, value in sections.items() if value]),
            },
            "sections": section_summaries,
            "report": report,
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

    def _build_report(self, sections: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        observations = []
        for section, data in sections.items():
            highlights = data.get("highlights") or []
            if not highlights:
                continue
            observations.append(
                {
                    "section": section,
                    "title": SECTION_LABELS.get(section, section.replace("_", " ").title()),
                    "summary": highlights[0],
                    "supporting_points": highlights[1:],
                    "found_section": bool(data.get("found_section")),
                }
            )

        risk_watchlist = []
        for item in sections.get("risk_factors", {}).get("highlights") or []:
            risk_watchlist.append(item)

        return {
            "title": "SEC Filing Extractive Research Memo",
            "stance": "evidence_first_extract_only",
            "executive_summary": self._overall_summary(sections),
            "key_observations": observations,
            "risk_watchlist": risk_watchlist[:3],
            "limitations": [
                "This memo is generated from extracted filing text and should be reviewed against the source filing.",
                "It does not yet perform full numeric table parsing, valuation, or investment recommendation.",
            ],
        }


class EvidenceMemoSynthesizer(Protocol):
    def synthesize(self, filing: Dict[str, Any], analysis: Dict[str, Any], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        ...


@dataclass
class ExtractiveMemoSynthesizer:
    def synthesize(self, filing: Dict[str, Any], analysis: Dict[str, Any], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        report = dict(analysis.get("report") or {})
        report["title"] = f"{filing.get('ticker')} {filing.get('filing_type')} Evidence-Grounded Memo"
        report["memo_style"] = "extractive"
        report["citations"] = self._section_citations(evidence)
        return {
            "report": report,
            "metadata": {
                "memo_synthesizer": "extractive",
                "memo_status": "extractive_fallback",
            },
        }

    def _section_citations(self, evidence: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        citations: Dict[str, List[str]] = {}
        for item in evidence:
            if item.get("kind") != "filing_excerpt":
                continue
            section = str(item.get("section") or "matched_text")
            citation_id = str(item.get("citation_id") or "")
            if citation_id:
                citations.setdefault(section, []).append(citation_id)
        return citations


@dataclass
class LangChainEvidenceMemoSynthesizer:
    model_config_store: ModelConfigStore
    fallback: EvidenceMemoSynthesizer = field(default_factory=ExtractiveMemoSynthesizer)

    def synthesize(self, filing: Dict[str, Any], analysis: Dict[str, Any], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        config = self.model_config_store.get()
        if not self._is_configured(config):
            result = self.fallback.synthesize(filing, analysis, evidence)
            result["metadata"]["memo_status"] = "model_not_configured"
            return result

        try:
            llm_report = self._synthesize_with_llm(filing, analysis, evidence, config)
            return {
                "report": llm_report,
                "metadata": {
                    "memo_synthesizer": "langchain",
                    "memo_status": "model_synthesized",
                    "model": config.model,
                },
            }
        except Exception as exc:
            result = self.fallback.synthesize(filing, analysis, evidence)
            result["metadata"]["memo_status"] = "model_failed"
            result["metadata"]["memo_error"] = str(exc)
            return result

    def _synthesize_with_llm(
        self,
        filing: Dict[str, Any],
        analysis: Dict[str, Any],
        evidence: List[Dict[str, Any]],
        config: ModelAPIConfig,
    ) -> Dict[str, Any]:
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise RuntimeError("langchain-openai is required for memo synthesis") from exc

        llm_kwargs = {
            "model": config.model,
            "api_key": config.api_key,
            "temperature": config.temperature,
        }
        if config.base_url:
            llm_kwargs["base_url"] = config.base_url

        llm = ChatOpenAI(**llm_kwargs)
        response = llm.invoke(
            [
                SystemMessage(
                    content=(
                        "You are a financial research memo writer. Use only the provided SEC filing evidence. "
                        "Do not invent facts, numbers, valuation, price targets, or recommendations. "
                        "Every key observation and risk must cite evidence ids like [E1]. "
                        "Return only valid JSON matching this schema: "
                        "{\"title\":\"string\",\"memo_style\":\"llm_evidence_grounded\","
                        "\"executive_summary\":\"string\",\"key_observations\":[{\"title\":\"string\","
                        "\"summary\":\"string\",\"citations\":[\"E1\"]}],\"risk_watchlist\":[{\"risk\":\"string\","
                        "\"why_it_matters\":\"string\",\"citations\":[\"E2\"]}],\"limitations\":[\"string\"]}."
                    )
                ),
                HumanMessage(content=json.dumps(self._memo_payload(filing, analysis, evidence), ensure_ascii=False)),
            ]
        )
        content = str(getattr(response, "content", response)).strip()
        if content.startswith("```"):
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE | re.DOTALL)
        report = json.loads(content)
        return self._normalize_llm_report(report, filing)

    def _memo_payload(self, filing: Dict[str, Any], analysis: Dict[str, Any], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        excerpt_evidence = [
            {
                "citation_id": item.get("citation_id"),
                "section": item.get("section"),
                "note": item.get("note"),
                "excerpt": item.get("excerpt"),
            }
            for item in evidence
            if item.get("kind") == "filing_excerpt"
        ]
        return {
            "filing": filing,
            "extractive_summary": analysis.get("summary"),
            "extractive_sections": analysis.get("sections"),
            "evidence": excerpt_evidence[:12],
        }

    def _normalize_llm_report(self, report: Dict[str, Any], filing: Dict[str, Any]) -> Dict[str, Any]:
        observations = report.get("key_observations") or []
        risks = report.get("risk_watchlist") or []
        return {
            "title": str(report.get("title") or f"{filing.get('ticker')} {filing.get('filing_type')} Research Memo"),
            "memo_style": "llm_evidence_grounded",
            "executive_summary": str(report.get("executive_summary") or ""),
            "key_observations": [
                {
                    "title": str(item.get("title") or "Observation"),
                    "summary": str(item.get("summary") or ""),
                    "citations": list(item.get("citations") or []),
                }
                for item in observations
                if isinstance(item, dict)
            ],
            "risk_watchlist": [
                {
                    "risk": str(item.get("risk") or item.get("summary") or ""),
                    "why_it_matters": str(item.get("why_it_matters") or ""),
                    "citations": list(item.get("citations") or []),
                }
                for item in risks
                if isinstance(item, dict)
            ],
            "limitations": list(
                report.get("limitations")
                or [
                    "Generated from provided SEC filing excerpts only.",
                    "Not investment advice; review source filing before relying on conclusions.",
                ]
            ),
        }

    def _is_configured(self, config: ModelAPIConfig) -> bool:
        return bool(config.model and config.api_key)


@dataclass
class CitationValidationResult:
    status: str
    valid_citations: List[str]
    referenced_citations: List[str]
    invalid_citations: List[str]
    missing_citation_items: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "valid_citations": self.valid_citations,
            "referenced_citations": self.referenced_citations,
            "invalid_citations": self.invalid_citations,
            "missing_citation_items": self.missing_citation_items,
        }


@dataclass
class MemoCitationValidator:
    def validate(self, report: Dict[str, Any], evidence: List[Dict[str, Any]]) -> CitationValidationResult:
        valid = sorted(
            {
                str(item["citation_id"])
                for item in evidence
                if item.get("kind") == "filing_excerpt" and item.get("citation_id")
            },
            key=self._citation_sort_key,
        )
        valid_set = set(valid)
        referenced = sorted(self._report_citations(report), key=self._citation_sort_key)
        invalid = [citation for citation in referenced if citation not in valid_set]
        missing = self._missing_required_citations(report)
        status = "passed" if not invalid and not missing else "warning"
        return CitationValidationResult(
            status=status,
            valid_citations=valid,
            referenced_citations=referenced,
            invalid_citations=invalid,
            missing_citation_items=missing,
        )

    def _report_citations(self, report: Dict[str, Any]) -> set[str]:
        citations: set[str] = set()
        for item in report.get("key_observations") or []:
            if isinstance(item, dict):
                citations.update(str(citation) for citation in item.get("citations") or [])
        for item in report.get("risk_watchlist") or []:
            if isinstance(item, dict):
                citations.update(str(citation) for citation in item.get("citations") or [])
        section_citations = report.get("citations")
        if isinstance(section_citations, dict):
            for values in section_citations.values():
                citations.update(str(citation) for citation in values or [])
        return citations

    def _missing_required_citations(self, report: Dict[str, Any]) -> List[str]:
        if report.get("memo_style") != "llm_evidence_grounded":
            return []
        missing: List[str] = []
        for index, item in enumerate(report.get("key_observations") or [], start=1):
            if isinstance(item, dict) and not item.get("citations"):
                missing.append(f"key_observations[{index}]")
        for index, item in enumerate(report.get("risk_watchlist") or [], start=1):
            if isinstance(item, dict) and not item.get("citations"):
                missing.append(f"risk_watchlist[{index}]")
        return missing

    def _citation_sort_key(self, citation: str) -> tuple[int, str]:
        match = re.fullmatch(r"E(\d+)", citation)
        if not match:
            return (10_000, citation)
        return (int(match.group(1)), citation)


@dataclass
class MarkdownMemoArtifactWriter:
    artifact_root: str | Path = Path(".autofin/artifacts")

    def __post_init__(self) -> None:
        self.artifact_root = Path(self.artifact_root)

    def write(self, filing: Dict[str, Any], report: Dict[str, Any], evidence: List[Dict[str, Any]]) -> Dict[str, Any]:
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        path = self.artifact_root / self._filename(filing)
        content = self._render_markdown(filing, report, evidence)
        path.write_text(content, encoding="utf-8")
        return {
            "kind": "markdown_memo",
            "path": str(path),
            "format": "markdown",
        }

    def _filename(self, filing: Dict[str, Any]) -> str:
        ticker = self._slug(str(filing.get("ticker") or "filing"))
        filing_type = self._slug(str(filing.get("filing_type") or "filing"))
        accession = self._slug(str(filing.get("accession_number") or "memo"))
        return f"{ticker}_{filing_type}_{accession}_memo.md"

    def _render_markdown(self, filing: Dict[str, Any], report: Dict[str, Any], evidence: List[Dict[str, Any]]) -> str:
        lines = [
            f"# {report.get('title') or filing.get('ticker') or 'Research Memo'}",
            "",
            f"- Company: {filing.get('company_name') or filing.get('ticker')}",
            f"- Ticker: {filing.get('ticker')}",
            f"- Filing: {filing.get('filing_type')}",
            f"- Filed: {filing.get('filing_date')}",
            f"- Source: {filing.get('document_url')}",
            f"- Memo style: {report.get('memo_style') or 'unknown'}",
            "",
            "## Executive Summary",
            "",
            str(report.get("executive_summary") or ""),
            "",
            "## Key Observations",
            "",
        ]
        for item in report.get("key_observations") or []:
            if not isinstance(item, dict):
                continue
            citations = self._format_citations(item.get("citations") or [])
            lines.extend(
                [
                    f"### {item.get('title') or item.get('section') or 'Observation'} {citations}".rstrip(),
                    "",
                    str(item.get("summary") or ""),
                    "",
                ]
            )
            for point in item.get("supporting_points") or []:
                lines.append(f"- {point}")
            if item.get("supporting_points"):
                lines.append("")

        lines.extend(["## Risk Watchlist", ""])
        for item in report.get("risk_watchlist") or []:
            if isinstance(item, str):
                lines.extend([f"- {item}", ""])
                continue
            if not isinstance(item, dict):
                continue
            citations = self._format_citations(item.get("citations") or [])
            lines.extend(
                [
                    f"### {item.get('risk') or 'Risk'} {citations}".rstrip(),
                    "",
                    str(item.get("why_it_matters") or ""),
                    "",
                ]
            )

        lines.extend(["## Limitations", ""])
        for item in report.get("limitations") or []:
            lines.append(f"- {item}")

        lines.extend(["", "## Evidence References", ""])
        for item in evidence:
            if item.get("kind") != "filing_excerpt":
                continue
            lines.extend(
                [
                    f"### {item.get('citation_id')} - {item.get('section')}",
                    "",
                    str(item.get("note") or ""),
                    "",
                    f"> {item.get('excerpt') or ''}",
                    "",
                    f"Source: {item.get('url')}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip() + "\n"

    def _format_citations(self, citations: List[str]) -> str:
        if not citations:
            return ""
        return " ".join(f"[{citation}]" for citation in citations)

    def _slug(self, value: str) -> str:
        slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-").lower()
        return slug or "memo"


class SecFilingAnalysisSkill(Skill):
    name = "sec_filing_analysis"
    description = "Analyze SEC 10-K or 10-Q filings and return a summary with evidence."
    permissions = PermissionSet(
        network=["sec.gov"],
        filesystem=["write_temp"],
        secrets=[],
    )

    def __init__(
        self,
        client: SECClient | None = None,
        analyzer: FilingDocumentAnalyzer | None = None,
        memo_synthesizer: EvidenceMemoSynthesizer | None = None,
        citation_validator: MemoCitationValidator | None = None,
        artifact_writer: MarkdownMemoArtifactWriter | None = None,
    ) -> None:
        self.client = client or SECClient()
        self.analyzer = analyzer or FilingDocumentAnalyzer()
        self.memo_synthesizer = memo_synthesizer or ExtractiveMemoSynthesizer()
        self.citation_validator = citation_validator or MemoCitationValidator()
        self.artifact_writer = artifact_writer or MarkdownMemoArtifactWriter()

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
                "citation_id": f"E{index}",
                "source": "sec.gov",
                "kind": "filing_excerpt",
                "section": excerpt.section or "matched_text",
                "note": self.analyzer._sentence_summary(excerpt.text),
                "excerpt": excerpt.text[:700],
                "url": filing.document_url,
            }
            for index, excerpt in enumerate(analysis.pop("excerpts"), start=1)
        ]
        evidence = [
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
        ]
        filing_info = {
            "ticker": filing.ticker,
            "company_name": filing.company_name,
            "cik": filing.cik,
            "filing_type": filing.filing_type,
            "filing_date": filing.filing_date,
            "report_date": filing.report_date,
            "accession_number": filing.accession_number,
            "primary_document": filing.primary_document,
            "document_url": filing.document_url,
        }
        analysis["extractive_report"] = ExtractiveMemoSynthesizer().synthesize(filing_info, analysis, evidence)["report"]
        memo_result = self.memo_synthesizer.synthesize(filing_info, analysis, evidence)
        report = memo_result["report"]
        memo_metadata = memo_result["metadata"]
        citation_validation = self.citation_validator.validate(report, evidence)
        if citation_validation.status != "passed" and memo_metadata.get("memo_status") == "model_synthesized":
            memo_metadata["memo_status"] = "model_synthesized_with_warnings"
        artifact = self.artifact_writer.write(filing_info, report, evidence)
        analysis["report"] = report
        analysis["memo_metadata"] = memo_metadata
        analysis["citation_validation"] = citation_validation.to_dict()
        analysis["artifacts"] = [artifact]
        warnings = [
            "Automated filing analysis is evidence-grounded and is not investment advice.",
            "Numeric statement parsing is planned for a later iteration.",
        ]
        if citation_validation.status != "passed":
            warnings.append("Memo citation validation produced warnings; inspect analysis.citation_validation.")
        return SkillResult(
            data={
                **filing_info,
                "summary": analysis["summary"],
                "analysis": analysis,
                "status": analysis["status"],
            },
            evidence=evidence,
            warnings=warnings,
        )
