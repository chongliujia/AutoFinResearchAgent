from autofin.runtime import ResearchOrchestrator, SkillRegistry, TraceLogger
from autofin.schemas import ResearchTask
from autofin.skills import SecFilingAnalysisSkill


def test_orchestrator_runs_langgraph_skill_flow(tmp_path):
    registry = SkillRegistry([SecFilingAnalysisSkill()])
    orchestrator = ResearchOrchestrator(
        registry,
        trace_logger=TraceLogger(tmp_path / "traces.jsonl"),
    )
    task = ResearchTask(
        objective="Analyze AAPL 10-K",
        inputs={"ticker": "AAPL", "filing_type": "10-K"},
    )

    state = orchestrator.run(task)

    assert state["selected_skill"] == "sec_filing_analysis"
    assert state["permission_status"] == "approved"
    assert state["result"]["data"]["ticker"] == "AAPL"
    assert (tmp_path / "traces.jsonl").exists()
