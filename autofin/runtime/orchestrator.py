from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any, Dict, TypedDict

from autofin.runtime.permissions import PermissionPolicy
from autofin.runtime.skill_registry import SkillRegistry
from autofin.runtime.trace import TraceLogger
from autofin.sandbox.executor import SandboxExecutor
from autofin.schemas import ResearchTask


class ResearchState(TypedDict, total=False):
    task: ResearchTask
    trace_id: str
    selected_skill: str
    permission_status: str
    result: Dict[str, Any]


class ResearchOrchestrator:
    """LangGraph-backed workflow for auditable financial research tasks."""

    def __init__(
        self,
        registry: SkillRegistry,
        executor: SandboxExecutor | None = None,
        policy: PermissionPolicy | None = None,
        trace_logger: TraceLogger | None = None,
    ) -> None:
        self.registry = registry
        self.executor = executor or SandboxExecutor()
        self.policy = policy or PermissionPolicy(allowed_network=["sec.gov"])
        self.trace_logger = trace_logger or TraceLogger()

    def build_graph(self):
        try:
            from langgraph.graph import END, START, StateGraph
        except ImportError as exc:
            raise RuntimeError(
                "LangGraph is required to run the research orchestrator. "
                "Install the project dependencies first."
            ) from exc

        graph = StateGraph(ResearchState)
        graph.add_node("start_trace", self._start_trace)
        graph.add_node("select_skill", self._select_skill)
        graph.add_node("check_permissions", self._check_permissions)
        graph.add_node("execute_skill", self._execute_skill)
        graph.add_node("write_result_trace", self._write_result_trace)

        graph.add_edge(START, "start_trace")
        graph.add_edge("start_trace", "select_skill")
        graph.add_edge("select_skill", "check_permissions")
        graph.add_edge("check_permissions", "execute_skill")
        graph.add_edge("execute_skill", "write_result_trace")
        graph.add_edge("write_result_trace", END)
        return graph.compile()

    def run(self, task: ResearchTask) -> Dict[str, Any]:
        app = self.build_graph()
        return self._jsonable(app.invoke({"task": task}))

    def _start_trace(self, state: ResearchState) -> ResearchState:
        trace_id = self.trace_logger.start_run()
        self.trace_logger.write(trace_id, "task_received", {"task": state["task"]})
        return {"trace_id": trace_id}

    def _select_skill(self, state: ResearchState) -> ResearchState:
        task = state["task"]
        skill = self.registry.select(task.objective, task.skill_name)
        self.trace_logger.write(
            state["trace_id"],
            "skill_selected",
            {"skill": skill.name, "permissions": skill.permissions},
        )
        return {"selected_skill": skill.name}

    def _check_permissions(self, state: ResearchState) -> ResearchState:
        skill = self.registry.get(state["selected_skill"])
        self.policy.validate(skill.permissions)
        self.trace_logger.write(
            state["trace_id"],
            "permissions_approved",
            {"skill": skill.name, "permissions": skill.permissions},
        )
        return {"permission_status": "approved"}

    def _execute_skill(self, state: ResearchState) -> ResearchState:
        skill = self.registry.get(state["selected_skill"])
        result = self.executor.execute(skill, state["task"])
        result_dict = result.to_dict()
        self.trace_logger.write(
            state["trace_id"],
            "skill_executed",
            {"skill": skill.name, "result": result_dict},
        )
        return {"result": result_dict}

    def _write_result_trace(self, state: ResearchState) -> ResearchState:
        self.trace_logger.write(
            state["trace_id"],
            "run_completed",
            {"selected_skill": state["selected_skill"]},
        )
        return {}

    def _jsonable(self, value: Any) -> Any:
        if is_dataclass(value):
            return asdict(value)
        if isinstance(value, dict):
            return {key: self._jsonable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._jsonable(item) for item in value]
        return value
