from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


JsonDict = Dict[str, Any]


@dataclass(frozen=True)
class PermissionSet:
    network: List[str] = field(default_factory=list)
    filesystem: List[str] = field(default_factory=list)
    secrets: List[str] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return {
            "network": list(self.network),
            "filesystem": list(self.filesystem),
            "secrets": list(self.secrets),
        }


@dataclass(frozen=True)
class ResearchTask:
    objective: str
    inputs: JsonDict
    skill_name: Optional[str] = None


@dataclass(frozen=True)
class SkillResult:
    data: JsonDict
    evidence: List[JsonDict] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> JsonDict:
        return {
            "data": self.data,
            "evidence": self.evidence,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class TraceEvent:
    event_type: str
    payload: JsonDict
