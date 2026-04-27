from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict

from autofin.schemas import PermissionSet, SkillResult


class Skill(ABC):
    """Reusable financial research capability with declared permissions."""

    name: str
    description: str
    permissions: PermissionSet

    @abstractmethod
    def run(self, inputs: Dict[str, Any]) -> SkillResult:
        raise NotImplementedError

    def to_langchain_tool(self):
        """Expose this skill as a LangChain StructuredTool."""
        try:
            from langchain.tools import StructuredTool
        except ImportError as exc:
            raise RuntimeError(
                "LangChain is required to expose skills as tools. "
                "Install the project dependencies first."
            ) from exc

        def _run(**kwargs: Any) -> Dict[str, Any]:
            return self.run(dict(kwargs)).to_dict()

        return StructuredTool.from_function(
            func=_run,
            name=self.name,
            description=self.description,
        )
