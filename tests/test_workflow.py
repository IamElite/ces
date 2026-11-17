"""Behavioral tests for CES v3: skills/ces/workflow.py and the package around it.

Standard library only.

    python3 -m unittest discover -s tests -v

The headline test drives a full complex-task lifecycle through the real command
line: init, eleven stages, findings, decisions, a failed then passed verification,
a blocker, and completion with archiving. The rest covers the guards, state
integrity, the strategy catalog, the rubric weights, and the consistency between
SKILL.md, strategies.json, rubric.md and the plugin metadata.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SKILL_DIR = os.path.join(REPO, "skills", "ces")
WORKFLOW = os.path.join(SKILL_DIR, "workflow.py")
sys.path.insert(0, SKILL_DIR)

import workflow as W  # noqa: E402

EXPECTED_VERSION = "3.0.0"

# SKILL.md heading name -> workflow.STAGES id, in lifecycle order.
HEADING_TO_STAGE = [
    ("Understand", "understand"),
    ("Classify", "classify"),
    ("Inspect", "inspect"),
    ("Diagnose", "diagnose"),
    ("Select", "select"),
    ("Plan", "plan"),
    ("Implement", "implement"),
    ("Verify", "verify"),
    ("Evaluate", "evaluate"),
    ("Final review", "review"),
    ("Report", "report"),
]


def cli(*args):
    return subprocess.run([sys.executable, WORKFLOW] + [str(a) for a in args],
                          capture_output=True, text=True)


def read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def load_state(project):
    with open(os.path.join(project, ".ces", "workflow.json"), encoding="utf-8") as fh:
        return json.load(fh)


class TempDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="ces-test-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def ok(self, *args):
        r = cli(*args)
        self.assertEqual(r.returncode, 0, "workflow.py %s failed:\n%s%s"
                         % (" ".join(map(str, args)), r.stdout, r.stderr))
        return r.stdout

    def fails(self, *args):
        r = cli(*args)
        self.assertEqual(r.returncode, 2, "workflow.py %s should exit 2, got %d:\n%s"
                         % (" ".join(map(str, args)), r.returncode, r.stdout))
        self.assertIn("error:", r.stderr)
        return r.stderr


class SkillPackage(unittest.TestCase):
    """The package structure, the orchestrator frontmatter, and SKILL.md/engine consistency."""

    @classmethod
    def setUpClass(cls):
        cls.skill = read(os.path.join(SKILL_DIR, "SKILL.md"))

    def test_skill_files_are_exactly_the_architecture(self):
        files = sorted(name for name in os.listdir(SKILL_DIR) if name != "__pycache__")
        self.assertEqual(files, ["SKILL.md", "rubric.md", "strategies.json", "workflow.py"])

    def test_frontmatter(self):
        self.assertTrue(self.skill.startswith("---\n"))
        fm = self.skill.split("\n---\n", 1)[0]
        self.assertRegex(fm, r"(?m)^name:\s*ces$")
        self.assertRegex(fm, r"(?m)^description:\s*>-?$")
        self.assertIn('version: "%s"' % EXPECTED_VERSION, fm)

    def test_skill_headings_match_engine_stages(self):
        headings = re.findall(r"^### Stage (\d+) - (.+)$", self.skill, re.M)
        self.assertEqual(len(headings), len(HEADING_TO_STAGE))
        for index, ((num, name), (_, stage_id)) in enumerate(zip(headings, HEADING_TO_STAGE)):
            self.assertEqual(int(num), index + 1, "stage numbering must run 1..11 in order")
            self.assertEqual(name, HEADING_TO_STAGE[index][0], "heading out of order")
            self.assertEqual(W.STAGES[index], stage_id, "SKILL.md stage %s disagrees with the engine" % name)

    def test_skill_documents_the_engine(self):
        for needle in ("workflow.py", "strategies.json", "rubric.md",
                       "init --task", "next", "resume", "score --strategy"):
            self.assertIn(needle, self.skill, "SKILL.md does not mention %r" % needle)

    def test_skill_requires_professional_concise_formatted_code(self):
        for needle in ("Professional implementation and logic", "Concise, right-sized code",
                       "Formatting and style", "Debugging hygiene",
                       "Reference-repository reimplementation", "behavior", "matrix"):
            self.assertIn(needle, self.skill, "SKILL.md is missing %r" % needle)
    def test_skill_requires_meaningful_operational_activity_logging(self):
        for needle in ("Meaningful operational activity logging",
                       "owner-facing record", "task was accepted or added",
                       "task started", "task completed or failed",
                       "Emit each event once", "Do not log every loop iteration",
                       "owner visibility with low noise", "Never log passwords"):
            self.assertIn(needle, self.skill, "SKILL.md is missing logging rule %r" % needle)


    def test_engine_compiles_and_matches_docs(self):
        self.assertEqual(len(W.STAGES), 11)
        self.assertEqual(W.STATE_VERSION, 1)
        self.assertEqual([s for s, _ in HEADING_TO_STAGE],
                         [h for h, _ in HEADING_TO_STAGE])  # self-check of the table


class StrategyCatalog(TempDir):
    """strategies.json through the real loader and the real CLI."""

    def test_catalog_is_valid_and_populated(self):
        data = W.load_strategies()
        ids = [s["id"] for s in data["strategies"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertGreaterEqual(len(ids), 14)
        for sid in ("bug-investigation", "feature-implementation", "refactoring",
                    "telegram-bot-development", "media-processing", "deployment-troubleshooting",
                    "code-review", "behavior-preserving-reimplementation"):
            self.assertIn(sid, ids, "the spec's core strategies must exist")

    def test_every_strategy_is_well_formed(self):
        data = W.load_strategies()
        for s in data["strategies"]:
            with self.subTest(strategy=s["id"]):
                for field in ("name", "matches", "when", "min_complexity", "verify"):
                    self.assertTrue(s.get(field), "%s missing %s" % (s["id"], field))
                self.assertIn(s["min_complexity"], W.COMPLEXITIES)
                self.assertGreaterEqual(len(s["verify"]), 2, "each strategy needs a real checklist")
                for dim in (s.get("rubric_emphasis") or {}):
                    self.assertIn(dim, W.RUBRIC_DIMENSIONS)
                for stage in (s.get("stage_focus") or {}):
                    self.assertIn(stage, W.STAGES)

    def test_cli_lists_and_details(self):
        out = self.ok("strategies")
        self.assertIn("bug-investigation", out)
        self.assertIn("telegram-bot-development", out)
        detail = self.ok("strategies", "bug-investigation")
        self.assertIn("Reproduce first", detail)
        self.assertIn("rubric emphasis", detail)
        payload = json.loads(self.ok("strategies", "--json"))
        self.assertEqual(len(payload["strategies"]), len(W.load_strategies()["strategies"]))
        self.fails("strategies", "no-such-strategy")

    def test_behavior_reimplementation_strategy_requires_behavioral_parity(self):
        strategy = W.strategy_by_id(W.load_strategies(), "behavior-preserving-reimplementation")
        focus = strategy["stage_focus"]
        for stage in ("inspect", "diagnose", "plan", "implement", "verify"):
            self.assertIn(stage, focus)
        self.assertIn("behavior", focus["plan"].lower())
        self.assertIn("idiomatic", focus["implement"].lower())
        self.assertIn("parity", focus["verify"].lower())
        self.assertGreaterEqual(len(strategy["verify"]), 4)

    def test_validate(self):
        self.ok("validate")


class Rubric(TempDir):
    """rubric.md stays in sync with the engine's weights, and the scorer works."""

    def test_weights_table_matches_engine(self):
        rows = re.findall(r"^\| (\w+) \| (\d+) \|", read(os.path.join(SKILL_DIR, "rubric.md")), re.M)
        self.assertEqual([(k, int(w)) for k, w in rows], list(W.RUBRIC_WEIGHTS))
        self.assertEqual(sum(w for _, w in W.RUBRIC_WEIGHTS), 100)

    def test_effective_weights_default_to_100(self):
        weights = W.effective_weights(W.load_strategies())
        self.assertAlmostEqual(sum(w for _, w in weights), 100.0, places=6)

    def test_strategy_emphasis_renormalizes_and_shifts(self):
        data = W.load_strategies()
        bug = dict(W.effective_weights(data, "bug-investigation"))
        base = dict(W.effective_weights(data))
        self.assertAlmostEqual(sum(bug.values()), 100.0, places=6)
        self.assertGreater(bug["root_cause_accuracy"], base["root_cause_accuracy"] * 2)
        self.assertLess(bug["implementation_complexity"], base["implementation_complexity"])

    def test_score_full_twelve(self):
        out = self.ok("score",
                      "--functional-correctness", 10, "--requirement-completeness", 9,
                      "--root-cause-accuracy", 10, "--code-quality", 8, "--maintainability", 8,
                      "--security", 7, "--compatibility", 9, "--test-coverage", 8,
                      "--performance", 7, "--error-handling", 8, "--regression-risk", 9,
                      "--implementation-complexity", 9)
        # Hand-computed: sum(score x weight) / 100 = 870 / 100 = 87.0
        self.assertIn("weighted total: 87.0 / 100", out)

    def test_score_partial_renormalizes(self):
        out = self.ok("score", "--functional-correctness", 8, "--security", 8)
        # Both eights over any covered weight share renormalize to 80.0.
        self.assertIn("weighted total: 80.0 / 100", out)
        self.assertIn("2 of 12 dimensions", out)

    def test_score_emphasis_applies(self):
        # Unequal scores: bug emphasis boosts the heavily scored root-cause dimension
        # and shrinks the lightly scored one, so the total must rise.
        plain = self.ok("score", "--root-cause-accuracy", 9, "--implementation-complexity", 3)
        bug = self.ok("score", "--strategy", "bug-investigation",
                      "--root-cause-accuracy", 9, "--implementation-complexity", 3)
        total = lambda s: float(re.search(r"weighted total: ([\d.]+)", s).group(1))
        self.assertAlmostEqual(total(plain), 80.0, places=1)   # (9x10 + 3x2) / 12
        self.assertGreater(total(bug), total(plain) + 5, "bug emphasis must lift a cause-driven score")

    def test_score_guards(self):
        self.fails("score", "--functional-correctness", 11)
        self.fails("score", "--functional-correctness", -1)
        self.fails("score")
        out = self.ok("score", "--functional-correctness", 3, "--fatal")
        self.assertIn("FATAL", out)


class FullLifecycle(TempDir):
    """One complex task driven entirely through the CLI, the way SKILL.md runs it."""

    TASK = "Bulk uploads lose thumbnails in the telegram bot"

    def run_lifecycle(self):
        d = self.tmp
        self.ok("init", "--task", self.TASK, "--complexity", "complex",
                "--strategy", "telegram-bot-development",
                "--requirement", "thumbnails preserved", "--requirement", "captions unchanged",
                "--dir", d)
        state = load_state(d)
        self.assertEqual(state["complexity"], "complex")
        self.assertEqual(state["strategy"], "telegram-bot-development")
        self.assertEqual(state["requirements"], ["thumbnails preserved", "captions unchanged"])
        self.assertEqual(sorted(state["stages"]), sorted(W.STAGES))

        # next names the first stage and the command that closes it.
        out = self.ok("next", "--dir", d)
        self.assertIn("now: understand", out)
        self.assertIn("update understand --state done", out)

        self.ok("finding", "send_document drops the thumbnail attribute",
                "--evidence", "bot/upload.py:88", "--kind", "evidence", "--dir", d)
        self.ok("finding", "thumbnails must survive bulk and single uploads",
                "--kind", "requirement", "--dir", d)
        state = load_state(d)
        self.assertEqual(len(state["findings"]), 2)
        self.assertEqual(len(state["requirements"]), 3)  # 2 from init + 1 requirement finding

        for stage in ("understand", "classify", "inspect", "diagnose"):
            self.ok("update", stage, "--state", "done", "--dir", d)
        out = self.ok("next", "--dir", d)
        self.assertIn("now: select", out)

        out = self.ok("update", "select", "--state", "done",
                      "--strategy", "telegram-bot-development", "--dir", d)
        state = load_state(d)
        self.assertEqual(state["strategy"], "telegram-bot-development")
        self.assertIn("strategy: telegram-bot-development", state["decisions"][0]["choice"])

        self.ok("milestone", "reproduce the thumbnail loss", "--dir", d)
        self.ok("milestone", "--done", 1, "--dir", d)
        self.ok("update", "plan", "--state", "done",
                "--note", "the fix and regression test are sequenced", "--dir", d)

        self.ok("file", "bot/upload.py", "--dir", d)
        self.ok("file", "bot/upload.py", "--dir", d)  # idempotent
        self.ok("file", "tests/test_upload.py", "--dir", d)
        state = load_state(d)
        self.assertEqual(state["files_changed"], ["bot/upload.py", "tests/test_upload.py"])

        self.ok("update", "implement", "--state", "done", "--dir", d)
        self.ok("verify", "pytest tests/test_upload.py", "--result", "fail",
                "--notes", "thumbnail assertion fails", "--dir", d)
        self.ok("verify", "pytest tests/test_upload.py", "--result", "pass", "--dir", d)
        state = load_state(d)
        self.assertEqual([v["result"] for v in state["verifications"]], ["fail", "pass"])

        for stage in ("verify", "evaluate", "review", "report"):
            self.ok("update", stage, "--state", "done", "--dir", d)
        out = self.ok("next", "--dir", d)
        self.assertIn("all eleven stages are closed", out)

        self.ok("blocker", "staging bot token expired", "--dir", d)
        self.fails("complete", "--dir", d)
        self.ok("blocker", "--resolve", 1, "--dir", d)
        out = self.ok("complete", "--dir", d)
        self.assertIn("workflow complete", out)
        self.assertIn(self.TASK, out)
        return d, out

    def test_headline_full_lifecycle(self):
        d, out = self.run_lifecycle()
        self.assertIn("bot/upload.py", out)
        self.assertIn("[fail] pytest tests/test_upload.py", out)
        self.assertIn("[pass] pytest tests/test_upload.py", out)
        self.assertIn("Never commit, push or deploy", out)
        # Active state is gone, the archive exists and carries the whole record.
        self.assertFalse(os.path.exists(os.path.join(d, ".ces", "workflow.json")))
        archives = os.listdir(os.path.join(d, ".ces", "archive"))
        self.assertEqual(len(archives), 1)
        archived = json.loads(read(os.path.join(d, ".ces", "archive", archives[0])))
        self.assertEqual(archived["task"], self.TASK)
        self.assertEqual(archived["stages"]["report"]["state"], "done")
        # No temp files left behind by the atomic writer.
        self.assertEqual([f for f in os.listdir(os.path.join(d, ".ces")) if f.endswith(".tmp")], [])

    def test_resume_reflects_state_mid_flight(self):
        d = self.tmp
        self.ok("init", "--task", "multi-session migration", "--complexity", "complex",
                "--dir", d)
        self.ok("update", "understand", "--state", "done", "--dir", d)
        self.ok("update", "classify", "--state", "done", "--dir", d)
        self.ok("decision", "stage the migration in batches", "--reason", "row count too high for one pass", "--dir", d)
        out = self.ok("resume", "--dir", d)
        self.assertIn("stage the migration in batches", out)
        self.assertIn("continue from: inspect", out)
        self.assertIn("git", out.lower(), "resume must point the agent at the repository truth")
        payload = json.loads(self.ok("resume", "--json", "--dir", d))
        self.assertEqual(payload["stage"], "inspect")
        self.assertEqual(payload["decisions"][0]["choice"], "stage the migration in batches")

    def test_json_state_tracks_everything(self):
        d = self.tmp
        self.ok("init", "--task", "track it", "--complexity", "medium", "--dir", d)
        self.ok("milestone", "first working slice", "--dir", d)
        self.ok("remaining", "write the changelog entry", "--dir", d)
        state = load_state(d)
        self.assertEqual(len(state["milestones"]), 1)
        self.assertFalse(state["milestones"][0]["done"])
        self.ok("milestone", "--done", 1, "--dir", d)
        self.ok("remaining", "--done", 1, "--dir", d)
        state = load_state(d)
        self.assertTrue(state["milestones"][0]["done"])
        self.assertTrue(state["remaining"][0]["done"])


class Guards(TempDir):
    def test_small_tasks_never_create_state(self):
        self.fails("init", "--task", "tiny", "--complexity", "small", "--dir", self.tmp)
        self.assertEqual(os.listdir(self.tmp), [])
        out = self.ok("plan", "--complexity", "small")
        self.assertIn("no state", out)

    def test_init_refuses_overwrite_without_force(self):
        d = self.tmp
        self.ok("init", "--task", "first", "--complexity", "medium", "--dir", d)
        first = load_state(d)["task"]
        self.fails("init", "--task", "second", "--complexity", "medium", "--dir", d)
        self.assertEqual(load_state(d)["task"], first)
        out = self.ok("init", "--task", "second", "--complexity", "medium", "--force", "--dir", d)
        self.assertIn("archived the previous workflow", out)
        self.assertEqual(load_state(d)["task"], "second")
        self.assertEqual(len(os.listdir(os.path.join(d, ".ces", "archive"))), 1)

    def test_init_validates_strategy(self):
        self.fails("init", "--task", "x", "--complexity", "medium", "--strategy", "nope",
                   "--dir", self.tmp)
        self.ok("init", "--task", "x", "--complexity", "medium", "--strategy", "api-integration",
                "--dir", self.tmp)

    def test_commands_without_state_fail_cleanly(self):
        for argv in (("next",), ("status",), ("resume",), ("complete",), ("update", "inspect", "--state", "done")):
            self.fails(*(argv + ("--dir", self.tmp)))

    def test_lifecycle_moves_only_forward_one_stage_at_a_time(self):
        d = self.tmp
        self.ok("init", "--task", "x", "--complexity", "medium", "--dir", d)
        self.fails("update", "classify", "--state", "done", "--dir", d)
        self.assertEqual(load_state(d)["stages"]["understand"]["state"], "open")
        self.ok("update", "understand", "--state", "done", "--dir", d)
        self.fails("update", "understand", "--state", "done", "--dir", d)
        self.fails("update", "inspect", "--state", "done", "--dir", d)
        self.fails("update", "nonexistent-stage", "--state", "done", "--dir", d)

    def test_skip_requires_a_note_and_only_optional_stages_can_be_skipped(self):
        d = self.tmp
        self.ok("init", "--task", "x", "--complexity", "medium", "--dir", d)
        self.fails("update", "understand", "--state", "skip", "--note", "try to skip a core stage", "--dir", d)
        self.fails("update", "diagnose", "--state", "skip", "--dir", d)
        for stage in ("understand", "classify", "inspect"):
            self.ok("update", stage, "--state", "done", "--dir", d)
        self.ok("update", "diagnose", "--state", "skip", "--note", "not a bug, a feature", "--dir", d)
        self.assertEqual(load_state(d)["stages"]["diagnose"]["state"], "skip")

    def test_private_keys_are_refused_and_state_unchanged(self):
        d = self.tmp
        self.ok("init", "--task", "x", "--complexity", "medium", "--dir", d)
        before = read(os.path.join(d, ".ces", "workflow.json"))
        key = "-----BEGIN OPENSSH PRIVATE KEY-----b3BlbnNzaC1rZXk"
        self.fails("finding", key, "--dir", d)
        self.fails("blocker", "token: " + key, "--dir", d)
        self.assertEqual(read(os.path.join(d, ".ces", "workflow.json")), before,
                         "a refused record must not modify the state")

    def test_plan_writes_nothing(self):
        self.ok("plan", "--complexity", "complex", "--strategy", "refactoring")
        self.assertEqual(os.listdir(self.tmp), [])


class StateIntegrity(TempDir):
    def test_complete_refuses_open_core_stages_even_with_force(self):
        d = self.tmp
        self.ok("init", "--task", "incomplete work", "--complexity", "medium", "--dir", d)
        self.fails("complete", "--dir", d)
        self.fails("complete", "--force", "--dir", d)
        self.assertTrue(os.path.isfile(os.path.join(d, ".ces", "workflow.json")))
        self.assertFalse(os.path.exists(os.path.join(d, ".ces", "archive")))

    def test_complete_refuses_open_optional_stages_too(self):
        d = self.tmp
        self.ok("init", "--task", "open optional stage", "--complexity", "medium", "--dir", d)
        state = load_state(d)
        for stage in W.CORE_STAGES["medium"]:
            state["stages"][stage]["state"] = "done"
        W.save_state(state)
        err = self.fails("complete", "--dir", d)
        self.assertIn("lifecycle stage(s) remain open", err)
        self.assertTrue(os.path.isfile(os.path.join(d, ".ces", "workflow.json")))

    def test_state_cannot_redirect_writes_to_another_project(self):
        d = self.tmp
        outside = os.path.join(d, "other-project")
        os.makedirs(outside)
        self.ok("init", "--task", "path binding", "--complexity", "medium", "--dir", d)
        path = os.path.join(d, ".ces", "workflow.json")
        state = load_state(d)
        state["dir"] = outside
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        err = self.fails("update", "understand", "--state", "done", "--dir", d)
        self.assertIn("refusing to write outside", err)
        self.assertFalse(os.path.exists(os.path.join(outside, ".ces")))

    def test_semantically_corrupt_state_can_be_quarantined(self):
        d = self.tmp
        self.ok("init", "--task", "semantic recovery", "--complexity", "medium", "--dir", d)
        path = os.path.join(d, ".ces", "workflow.json")
        state = load_state(d)
        state["blockers"] = [{}]
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        err = self.fails("status", "--dir", d)
        self.assertIn("invalid blocker", err)
        out = self.ok("recover", "--dir", d)
        self.assertIn("quarantined", out)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(any(".corrupt-" in name for name in os.listdir(os.path.join(d, ".ces"))))

    def test_backup_lags_one_write_behind(self):
        d = self.tmp
        self.ok("init", "--task", "x", "--complexity", "medium", "--dir", d)
        self.assertFalse(os.path.exists(os.path.join(d, ".ces", "workflow.json.bak")))
        self.ok("update", "understand", "--state", "done", "--dir", d)
        backup = json.loads(read(os.path.join(d, ".ces", "workflow.json.bak")))
        self.assertEqual(backup["stages"]["understand"]["state"], "open",
                         "the backup holds the previous write, not the current one")

    def test_corrupted_state_is_kept_and_quarantined(self):
        d = self.tmp
        self.ok("init", "--task", "x", "--complexity", "medium", "--dir", d)
        self.ok("update", "understand", "--state", "done", "--dir", d)
        with open(os.path.join(d, ".ces", "workflow.json"), "w", encoding="utf-8") as fh:
            fh.write("{corrupted json")
        err = self.fails("status", "--dir", d)
        self.assertIn("corrupted", err)
        self.assertIn("recover", err)
        self.assertIn(".bak", err, "the error must mention the backup when one exists")
        # The corrupt file is still there until the user quarantines it.
        self.assertTrue(os.path.exists(os.path.join(d, ".ces", "workflow.json")))
        out = self.ok("recover", "--dir", d)
        self.assertIn("quarantined", out)
        self.assertFalse(os.path.exists(os.path.join(d, ".ces", "workflow.json")))
        quarantined = [f for f in os.listdir(os.path.join(d, ".ces")) if ".corrupt-" in f]
        self.assertEqual(len(quarantined), 1, "nothing is deleted")
        self.ok("init", "--task", "fresh", "--complexity", "medium", "--dir", d)

    def test_recover_refuses_a_healthy_state(self):
        d = self.tmp
        self.ok("init", "--task", "x", "--complexity", "medium", "--dir", d)
        self.fails("recover", "--dir", d)

    def test_failed_command_leaves_state_untouched(self):
        d = self.tmp
        self.ok("init", "--task", "x", "--complexity", "medium", "--dir", d)
        self.ok("file", "a.py", "--dir", d)
        before = read(os.path.join(d, ".ces", "workflow.json"))
        self.fails("file", "--remove", "b.py", "--dir", d)
        self.fails("update", "understand", "--state", "skip", "--dir", d)  # no note
        self.assertEqual(read(os.path.join(d, ".ces", "workflow.json")), before)

    def test_version_mismatch_is_reported(self):
        d = self.tmp
        self.ok("init", "--task", "x", "--complexity", "medium", "--dir", d)
        path = os.path.join(d, ".ces", "workflow.json")
        state = json.loads(read(path))
        state["version"] = 99
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
        err = self.fails("status", "--dir", d)
        self.assertIn("version 99", err)


class PluginMetadata(unittest.TestCase):
    """Plugin files, README and version consistency."""

    @classmethod
    def setUpClass(cls):
        cls.plugin = json.loads(read(os.path.join(REPO, ".claude-plugin", "plugin.json")))
        cls.marketplace = json.loads(read(os.path.join(REPO, ".claude-plugin", "marketplace.json")))
        cls.readme = read(os.path.join(REPO, "README.md"))

    def test_plugin_json(self):
        self.assertEqual(self.plugin["name"], "ces")
        self.assertEqual(self.plugin["version"], EXPECTED_VERSION)
        self.assertEqual(self.plugin["license"], "MIT")
        self.assertEqual(self.plugin["repository"], "https://github.com/IamElite/ces")
        self.assertTrue(self.plugin["description"].strip())
        self.assertTrue(self.plugin["keywords"])

    def test_marketplace_json(self):
        self.assertIn("marketplace.schema.json", self.marketplace.get("$schema", ""))
        self.assertEqual(self.marketplace["name"], "ces")
        entries = self.marketplace["plugins"]
        self.assertEqual(len(entries), 1)
        entry = entries[0]
        self.assertEqual(entry["name"], "ces")
        self.assertEqual(entry["source"], "./")
        self.assertTrue(entry["description"].strip())
        self.assertEqual(entry["license"], "MIT")

    def test_skill_folder_matches_metadata(self):
        self.assertTrue(os.path.isfile(os.path.join(REPO, "skills", "ces", "SKILL.md")))
        self.assertIn('version: "%s"' % EXPECTED_VERSION,
                      read(os.path.join(REPO, "skills", "ces", "SKILL.md")))

    def test_readme(self):
        self.assertIn("**Version:** %s" % EXPECTED_VERSION, self.readme)
        self.assertIn("npx skills add https://github.com/IamElite/ces/tree/dev/skills/ces --agent opencode --copy --yes", self.readme)
        self.assertIn(".agents/skills/ces/", self.readme)
        self.assertIn("npx skills update ces --yes", self.readme)
        self.assertIn("python -m unittest discover -s tests -v", self.readme)
        self.assertIn("workflow.py", self.readme)
        self.assertIn("strategies.json", self.readme)
        self.assertIn("rubric.md", self.readme)
        self.assertIn("MIT License. See", self.readme)

    def test_readme_documents_operational_logging_without_spam(self):
        for needle in ("Operational logging: owner visibility without spam",
                       "Task added", "Leech started", "Leech completed",
                       "Leech failed", "not every loop",
                       "Emit an event once", "who did what and what",
                       "SKILL.md"):
            self.assertIn(needle, self.readme, "README is missing operational logging guidance %r" % needle)

    def test_gitignore_excludes_state_but_not_sources(self):
        gi = read(os.path.join(REPO, ".gitignore"))
        self.assertIn(".ces/", gi)
        self.assertIn("__pycache__/", gi)
        # Source trees and files must never be ignored.
        for needed in ("skills/", "tests/", "SKILL.md"):
            self.assertNotIn(needed, gi, "%s must not be ignored" % needed)
        self.assertIsNone(re.search(r"(?m)^\*\.py\s*$", gi),
                          "a bare '*.py' ignore rule would hide the engine and the tests")


if __name__ == "__main__":
    unittest.main(verbosity=2)
