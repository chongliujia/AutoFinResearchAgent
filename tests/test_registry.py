from autofin.runtime import SkillRegistry
from autofin.skills import SecFilingAnalysisSkill


def test_registry_selects_sec_filing_skill_from_objective():
    registry = SkillRegistry([SecFilingAnalysisSkill()])

    skill = registry.select("Analyze AAPL 10-K risk factors")

    assert skill.name == "sec_filing_analysis"
