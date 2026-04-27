from __future__ import annotations

from autofin.schemas import ResearchTask, SkillResult
from autofin.skills.base import Skill


class SandboxExecutor:
    """Execution boundary for skills.

    The MVP runs in-process after permission validation. The next iteration should
    move this behind a subprocess/container policy with network and filesystem
    restrictions.
    """

    def execute(self, skill: Skill, task: ResearchTask) -> SkillResult:
        return skill.run(task.inputs)
