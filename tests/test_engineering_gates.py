"""Regression checks for CES repository-analysis and evidence gates."""
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "ces", "SKILL.md")
STRATEGIES = os.path.join(ROOT, "skills", "ces", "strategies.json")
README = os.path.join(ROOT, "README.md")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


class EngineeringGates(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = read(SKILL)
        cls.readme = read(README)
        with open(STRATEGIES, encoding="utf-8") as handle:
            cls.catalog = json.load(handle)
        cls.strategies = {item["id"]: item for item in cls.catalog["strategies"]}

    def test_skill_maps_repository_and_change_surface(self):
        for phrase in (
            "Repository map and change-surface analysis",
            "direct callers/callees",
            "dynamic",
            "public contracts",
            "Do not start implementation",
        ):
            self.assertIn(phrase, self.skill)

    def test_skill_requires_evidence_before_bug_fix(self):
        for phrase in (
            "Evidence gate before a fix",
            "first point where they diverge",
            "confirmed facts, hypotheses and unknowns",
            "A plausible explanation is not a confirmed root cause",
        ):
            self.assertIn(phrase, self.skill)

    def test_skill_escalates_repeated_failed_attempts(self):
        section = self.skill.split("Repeated-failure escalation.", 1)[1].split(
            "Feature integration diagnosis.", 1
        )[0]
        self.assertIn("After two unsuccessful fix attempts", section)
        self.assertIn("Never repeat a failed approach", section)
        self.assertIn("fresh root-cause review", section)

    def test_skill_requires_integration_and_regression_proof(self):
        for phrase in (
            "Feature integration diagnosis",
            "Before editing, write down the intended change boundary",
            "Proof of integration, not just local success",
            "regression test that would fail on the original bug",
            "A passing unit test for an isolated helper does not prove",
        ):
            self.assertIn(phrase, self.skill)

    def test_bug_strategy_enforces_investigation_and_escalation(self):
        strategy = self.strategies["bug-investigation"]
        self.assertIn("attempt ledger", strategy["stage_focus"]["diagnose"])
        self.assertIn("two unsuccessful fixes", strategy["stage_focus"]["diagnose"])
        self.assertTrue(any("regression test" in item for item in strategy["verify"]))
        self.assertTrue(any("first divergence" in item for item in strategy["verify"]))

    def test_feature_and_refactor_strategies_check_integration_surface(self):
        feature = self.strategies["feature-implementation"]
        refactor = self.strategies["refactoring"]
        self.assertIn("data/API contracts", feature["stage_focus"]["plan"])
        self.assertIn("existing callers", feature["stage_focus"]["verify"])
        self.assertIn("dynamic references", refactor["stage_focus"]["inspect"])
        self.assertTrue(any("dynamic references" in item for item in refactor["verify"]))

    def test_readme_explains_proportional_evidence_driven_work(self):
        self.assertIn("Evidence-driven repository engineering", self.readme)
        self.assertIn("After two unsuccessful attempts", self.readme)
        self.assertIn("small isolated edits", self.readme)


if __name__ == "__main__":
    unittest.main(verbosity=2)
