from __future__ import annotations

from typing import Dict, Iterable

from autofin.skills.base import Skill


class SkillRegistry:
    def __init__(self, skills: Iterable[Skill] | None = None) -> None:
        self._skills: Dict[str, Skill] = {}
        for skill in skills or []:
            self.register(skill)

    def register(self, skill: Skill) -> None:
        if skill.name in self._skills:
            raise ValueError(f"Skill already registered: {skill.name}")
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        try:
            return self._skills[name]
        except KeyError as exc:
            raise KeyError(f"Unknown skill: {name}") from exc

    def list(self) -> list[Skill]:
        return list(self._skills.values())

    def select(self, objective: str, requested_skill: str | None = None) -> Skill:
        if requested_skill:
            return self.get(requested_skill)

        lowered = objective.lower()
        if "10-k" in lowered or "10-q" in lowered or "sec" in lowered or "filing" in lowered:
            return self.get("sec_filing_analysis")

        if len(self._skills) == 1:
            return next(iter(self._skills.values()))

        raise ValueError(f"No skill matched objective: {objective}")

    def to_langchain_tools(self):
        return [skill.to_langchain_tool() for skill in self._skills.values()]
