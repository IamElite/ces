#!/usr/bin/env python3
"""workflow.py: the task state engine behind the CES coding skill.

CES follows one engineering lifecycle: understand, classify, inspect, diagnose,
select, plan, implement, verify, evaluate, review, report. This tool is the
deterministic memory for that lifecycle. The agent does the engineering work;
workflow.py records it, validates it and hands it back after a context loss.

    python3 workflow.py plan --complexity complex [--strategy S]     # preview the lifecycle. Writes nothing.
    python3 workflow.py init --task "..." --complexity medium --strategy bug-investigation
    python3 workflow.py next                                         # what to do now, and the exact command for it
    python3 workflow.py status                                       # one-screen summary of the active workflow
    python3 workflow.py update inspect --state done --note "..."     # close a stage (or --state skip --note "why")
    python3 workflow.py finding "..." [--evidence "..."] [--kind requirement|evidence|observation]
    python3 workflow.py decision "..." --reason "..."
    python3 workflow.py verify "pytest tests/test_api.py" --result pass|fail|blocked [--notes "..."]
    python3 workflow.py file src/api.py           # track a file the task touched
    python3 workflow.py file --remove src/api.py
    python3 workflow.py milestone "..."           # plan items, complex tasks
    python3 workflow.py milestone --done 1
    python3 workflow.py remaining "..."           # discovered outstanding work
    python3 workflow.py remaining --done 1
    python3 workflow.py blocker "..."             # something that blocks progress
    python3 workflow.py blocker --resolve 1
    python3 workflow.py resume                    # reorientation after a context loss
    python3 workflow.py complete                  # archive the finished workflow
    python3 workflow.py score --correctness 8 ... [--strategy S] [--fatal]
    python3 workflow.py strategies [id] [--json]  # inspect strategies.json
    python3 workflow.py validate                  # check the skill's configuration files

Every command takes --dir (the project directory that owns the state). Without
it, the current directory is used. State lives in <dir>/.ces/workflow.json,
archives in <dir>/.ces/archive/. Writes are atomic; the previous state is kept
as .ces/workflow.json.bak; a corrupted state is quarantined, never deleted.

Small tasks must not create state: init refuses --complexity small on purpose.

Python 3.8+, standard library only.
"""
import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SELF = os.path.abspath(__file__)
STRATEGIES_PATH = os.path.join(HERE, "strategies.json")
RUBRIC_PATH = os.path.join(HERE, "rubric.md")

STATE_DIRNAME = ".ces"
STATE_FILENAME = "workflow.json"
ARCHIVE_DIRNAME = "archive"
STATE_VERSION = 1

COMPLEXITIES = ("small", "medium", "complex")
FINDING_KINDS = ("requirement", "evidence", "observation")
VERIFY_RESULTS = ("pass", "fail", "blocked")

# The eleven lifecycle stages, in execution order. SKILL.md documents exactly
# these stages; tests/test_workflow.py checks the two stay identical.
STAGES = (
    "understand", "classify", "inspect", "diagnose", "select", "plan",
    "implement", "verify", "evaluate", "review", "report",
)

# Stages that must not be quietly skipped at each tracked complexity level.
CORE_STAGES = {
    "medium": ("understand", "classify", "inspect", "implement", "verify", "report"),
    "complex": STAGES,
}

# Mirrors the weights table in rubric.md. tests/test_workflow.py checks they agree.
RUBRIC_WEIGHTS = (
    ("functional_correctness", 18),
    ("requirement_completeness", 14),
    ("root_cause_accuracy", 10),
    ("code_quality", 8),
    ("maintainability", 8),
    ("security", 8),
    ("compatibility", 8),
    ("test_coverage", 8),
    ("performance", 6),
    ("error_handling", 6),
    ("regression_risk", 4),
    ("implementation_complexity", 2),
)
RUBRIC_DIMENSIONS = tuple(name for name, _ in RUBRIC_WEIGHTS)

# Strings that must never end up in the state file, whatever the text claims to be.
PRIVATE_KEY_MARKERS = (
    "-----BEGIN RSA PRIVATE KEY-----",
    "-----BEGIN OPENSSH PRIVATE KEY-----",
    "-----BEGIN EC PRIVATE KEY-----",
    "-----BEGIN DSA PRIVATE KEY-----",
    "-----BEGIN PRIVATE KEY-----",
    "-----BEGIN PGP PRIVATE KEY BLOCK-----",
)

STAGE_GUIDE = {
    "understand": (
        "Restate the objective, the expected output and what counts as done. "
        "Record every stated requirement with: finding \"...\" --kind requirement"
    ),
    "classify": (
        "Decide small, medium or complex from blast radius, unknowns and moving parts. "
        "Small work needs no state at all; let the class set the depth of every later stage"
    ),
    "inspect": (
        "Check git status first and preserve existing user work. Read the project's own "
        "instructions, then entry points, callers, configuration, dependencies and tests. "
        "Record concrete observations with evidence"
    ),
    "diagnose": (
        "Reproduce when practical, trace the real execution path and test hypotheses until "
        "the first divergence between actual and expected behavior is confirmed. "
        "Record confirmed causes with evidence, never a guess"
    ),
    "select": (
        "Compare the candidate strategies in strategies.json against the task and record "
        "the choice. Close this stage with --strategy <id> so the rubric emphasis follows"
    ),
    "plan": (
        "For complex work list milestones that each end in verifiable state. "
        "For medium work one or two are enough. Do not plan ceremony"
    ),
    "implement": (
        "Make the smallest complete change that fits the existing architecture and record "
        "every touched file. Preserve unrelated behavior and the user's uncommitted work"
    ),
    "verify": (
        "Run the most relevant existing checks first, then the checks this change demands. "
        "Record each command with its real result. Never record a result that did not happen"
    ),
    "evaluate": (
        "Score the change against rubric.md with the score command, using the task's "
        "strategy if one was selected. Address real weaknesses; record deliberate trade-offs as decisions"
    ),
    "review": (
        "Inspect the final diff for unrelated edits, debug output, secrets, compatibility "
        "breaks and regressions. Confirm the change stayed inside the requested scope"
    ),
    "report": (
        "Tell the user what changed, why, which files, what was tested, the verification "
        "results and the remaining limitations. Then run complete to archive the state"
    ),
}


class WorkflowError(Exception):
    """A user-visible error. The CLI exits with status 2 and no traceback."""


# ---------------------------------------------------------------- strategies

def load_strategies(path=STRATEGIES_PATH):
    """Load and validate strategies.json. Raises WorkflowError on any defect."""
    if not os.path.isfile(path):
        raise WorkflowError("strategies.json is missing at %s" % path)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        raise WorkflowError("strategies.json at %s is unreadable: %s" % (path, exc))
    if not isinstance(data, dict):
        raise WorkflowError("strategies.json must contain a JSON object")
    strategies = data.get("strategies")
    if not strategies:
        raise WorkflowError("strategies.json has no 'strategies' entries")
    ids = [s.get("id") for s in strategies]
    if any(not i for i in ids):
        raise WorkflowError("every strategy needs an id")
    if len(set(ids)) != len(ids):
        raise WorkflowError("strategies.json has a duplicate id")
    for s in strategies:
        for field in ("name", "matches", "when"):
            if not s.get(field):
                raise WorkflowError("strategy '%s' needs a %s" % (s.get("id"), field))
        if s.get("min_complexity") not in COMPLEXITIES:
            raise WorkflowError("strategy '%s' has an invalid min_complexity" % s["id"])
        focus = s.get("stage_focus", {})
        if not isinstance(focus, dict) or any(k not in STAGES for k in focus):
            raise WorkflowError("strategy '%s' has stage_focus keys outside the lifecycle stages" % s["id"])
        checks = s.get("verify", [])
        if not isinstance(checks, list) or any(not isinstance(c, str) or not c.strip() for c in checks):
            raise WorkflowError("strategy '%s' verify must be a list of non-empty strings" % s["id"])
        emphasis = s.get("rubric_emphasis", {})
        if not isinstance(emphasis, dict):
            raise WorkflowError("strategy '%s' rubric_emphasis must be an object" % s["id"])
        for dim, mult in emphasis.items():
            if dim not in RUBRIC_DIMENSIONS:
                raise WorkflowError("strategy '%s' emphasizes unknown rubric dimension '%s'" % (s["id"], dim))
            if not isinstance(mult, (int, float)) or not 0 < float(mult) <= 5:
                raise WorkflowError("strategy '%s' emphasis for '%s' must be a number in (0, 5]" % (s["id"], dim))
    return data


def strategy_by_id(data, sid):
    for s in data.get("strategies", []):
        if s["id"] == sid:
            return s
    known = ", ".join(s["id"] for s in data.get("strategies", []))
    raise WorkflowError("unknown strategy '%s'. Known strategies: %s" % (sid, known))


def effective_weights(data, sid=None):
    """Rubric weights for a strategy: defaults scaled by its emphasis, renormalized to 100.

    Returns a list of (dimension, weight) in RUBRIC_WEIGHTS order. Without a
    strategy the defaults from rubric.md are returned unchanged.
    """
    weights = {name: float(w) for name, w in RUBRIC_WEIGHTS}
    if sid is not None:
        strategy = strategy_by_id(data, sid)
        for dim, mult in (strategy.get("rubric_emphasis") or {}).items():
            weights[dim] *= float(mult)
    total = sum(weights.values())
    return [(name, weights[name] * 100.0 / total) for name, _ in RUBRIC_WEIGHTS]


# ---------------------------------------------------------------- text guard

def guard_text(label, text):
    """Refuse to store obvious private key material. Everything else is the user's call."""
    if text is None:
        return text
    for marker in PRIVATE_KEY_MARKERS:
        if marker in text:
            raise WorkflowError(
                "%s looks like private key material. The state file is plain JSON on disk; "
                "never store credentials in it. Reference the secret's location instead." % label
            )
    return text


# ---------------------------------------------------------------- state files

def state_paths(project_dir):
    ces_dir = os.path.join(project_dir, STATE_DIRNAME)
    return {
        "dir": ces_dir,
        "state": os.path.join(ces_dir, STATE_FILENAME),
        "backup": os.path.join(ces_dir, STATE_FILENAME + ".bak"),
        "archive": os.path.join(ces_dir, ARCHIVE_DIRNAME),
    }


def _read_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _validate_state(state, source):
    """Structural validation. source names the file for error messages."""
    if not isinstance(state, dict):
        raise WorkflowError("%s does not contain a state object" % source)
    if state.get("version") != STATE_VERSION:
        raise WorkflowError(
            "%s has state version %s; this tool understands version %s"
            % (source, state.get("version"), STATE_VERSION)
        )
    task = state.get("task")
    if not isinstance(task, str) or not task.strip():
        raise WorkflowError("%s has no task text" % source)
    if state.get("complexity") not in ("medium", "complex"):
        raise WorkflowError("%s has an invalid complexity %r" % (source, state.get("complexity")))
    stages = state.get("stages")
    if not isinstance(stages, dict) or set(stages) != set(STAGES):
        raise WorkflowError("%s does not track exactly the eleven lifecycle stages" % source)
    for name, entry in stages.items():
        if not isinstance(entry, dict) or entry.get("state") not in ("open", "done", "skip"):
            raise WorkflowError("%s has an invalid status for stage '%s'" % (source, name))
    for field in ("requirements", "findings", "decisions", "files_changed", "verifications",
                  "milestones", "remaining", "blockers"):
        value = state.get(field)
        if value is None:
            state[field] = []
        elif not isinstance(value, list):
            raise WorkflowError("%s field '%s' must be a list" % (source, field))
    if state.get("strategy") is not None:
        data = load_strategies()
        strategy_by_id(data, state["strategy"])
    return state


def load_state(project_dir):
    """Load the active state or raise WorkflowError with a recovery hint."""
    paths = state_paths(project_dir)
    path = paths["state"]
    if not os.path.isfile(path):
        raise WorkflowError(
            "no active CES workflow in %s. Run: python3 %s init --task \"...\" --complexity medium"
            % (project_dir, SELF)
        )
    try:
        state = _read_json(path)
    except (OSError, ValueError) as exc:
        hint = ""
        if os.path.isfile(paths["backup"]):
            hint = " A backup from the previous write exists at %s." % paths["backup"]
        raise WorkflowError(
            "%s is corrupted (%s). The file has been kept where it is; fix it by hand or "
            "quarantine it with: python3 %s recover --dir %s.%s"
            % (path, exc, SELF, project_dir, hint)
        )
    return _validate_state(state, path)


def _write_atomic(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def save_state(state):
    """Persist atomically, keeping the previous state as a .bak one write behind."""
    paths = state_paths(state["dir"])
    state["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    content = json.dumps(state, indent=1, sort_keys=False) + "\n"
    if os.path.isfile(paths["state"]):
        with open(paths["state"], encoding="utf-8") as fh:
            _write_atomic(paths["backup"], fh.read())
    _write_atomic(paths["state"], content)


def archive_state(state, project_dir):
    """Move the active state into .ces/archive/ and clear the active + backup files."""
    paths = state_paths(project_dir)
    os.makedirs(paths["archive"], exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    archived = os.path.join(paths["archive"], "%s-workflow.json" % stamp)
    n = 1
    while os.path.exists(archived):
        n += 1
        archived = os.path.join(paths["archive"], "%s-%d-workflow.json" % (stamp, n))
    shutil.copyfile(paths["state"], archived)
    os.remove(paths["state"])
    if os.path.isfile(paths["backup"]):
        os.remove(paths["backup"])
    return archived


def new_state(task, complexity, strategy, requirements, project_dir):
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    return {
        "version": STATE_VERSION,
        "created": now,
        "updated": now,
        "dir": os.path.abspath(project_dir),
        "task": task,
        "complexity": complexity,
        "strategy": strategy,
        "stages": {name: {"state": "open", "note": None} for name in STAGES},
        "requirements": list(requirements or []),
        "findings": [],
        "decisions": [],
        "files_changed": [],
        "verifications": [],
        "milestones": [],
        "remaining": [],
        "blockers": [],
    }


# ---------------------------------------------------------------- views

def stage_status(state, name):
    return state["stages"][name]["state"]


def current_stage(state):
    for name in STAGES:
        if stage_status(state, name) == "open":
            return name
    return None


def progress(state):
    closed = sum(1 for name in STAGES if stage_status(state, name) != "open")
    return closed, len(STAGES)


def warn(state):
    """Dynamic warnings appended to next/status output."""
    notes = []
    core = CORE_STAGES[state["complexity"]]
    skipped_core = [s for s in core if stage_status(state, s) == "skip"]
    if skipped_core:
        notes.append("warning: core stage(s) skipped for a %s task: %s"
                     % (state["complexity"], ", ".join(skipped_core)))
    if stage_status(state, "verify") != "done" and current_stage(state) == "verify" \
            and not state["verifications"]:
        notes.append("warning: no verification has been recorded yet; run a real check before closing this stage")
    if stage_status(state, "implement") == "done" and not state["files_changed"]:
        notes.append("warning: implement is closed but no changed files were recorded; record them with the file command")
    if state["blockers"]:
        notes.append("warning: %d open blocker(s); resolve them or complete with --force" % len(state["blockers"]))
    return notes


def _cmd(*parts):
    return "python3 \"%s\" %s" % (SELF, " ".join(str(p) for p in parts))


def print_header(state):
    closed, total = progress(state)
    bar = "#" * closed + "-" * (total - closed)
    print("task:    %s" % state["task"])
    print("mode:    %s | strategy: %s | stages %s [%s] %d/%d"
          % (state["complexity"], state["strategy"] or "(none selected)", bar,
             current_stage(state) or "all closed", closed, total))


def print_lists(state):
    done_ms = sum(1 for m in state["milestones"] if m["done"])
    counts = {"pass": 0, "fail": 0, "blocked": 0}
    for v in state["verifications"]:
        counts[v["result"]] += 1
    print("records: %d requirement(s), %d finding(s), %d decision(s), %d file(s)"
          % (len(state["requirements"]), len(state["findings"]), len(state["decisions"]),
             len(state["files_changed"])))
    print("         verifications %d pass / %d fail / %d blocked | milestones %d/%d | remaining %d | blockers %d"
          % (counts["pass"], counts["fail"], counts["blocked"], done_ms,
             len(state["milestones"]), len(state["remaining"]), len(state["blockers"])))


# ---------------------------------------------------------------- commands

def cmd_plan(args):
    if args.strategy:
        data = load_strategies()
        strategy_by_id(data, args.strategy)
    if args.complexity == "small":
        print("small task: no state, no milestones. Read strategies.json only if the task matches "
              "a specific strategy, do the work directly, verify, report. Do not run init.")
        return 0
    core = CORE_STAGES.get(args.complexity, STAGES)
    print("%s task lifecycle (%d stages, %d core):" % (args.complexity, len(STAGES), len(core)))
    for i, name in enumerate(STAGES, 1):
        marker = "core" if name in core else "skip-able"
        print("  %2d. %-9s %-8s %s" % (i, name, marker, STAGE_GUIDE[name]))
    print("")
    print("start it: %s" % _cmd("init", "--task \"...\"", "--complexity", args.complexity,
                                 "--strategy <id>"))
    return 0


def cmd_init(args):
    if args.complexity == "small":
        raise WorkflowError(
            "small tasks must not create workflow state. Run: python3 %s plan --complexity small"
            % SELF
        )
    guard_text("task", args.task)
    for req in args.requirement or []:
        guard_text("requirement", req)
    data = load_strategies()
    if args.strategy:
        strategy_by_id(data, args.strategy)
    project_dir = os.path.abspath(args.dir)
    paths = state_paths(project_dir)
    if os.path.exists(paths["state"]):
        if not args.force:
            raise WorkflowError(
                "%s already holds an active workflow. Inspect it with status, finish it with "
                "complete, or replace it with --force (the old state is archived first)."
                % paths["state"]
            )
        old = _read_json(paths["state"])
        old["dir"] = project_dir
        archived = archive_state(old, project_dir)
        print("archived the previous workflow to %s" % archived)
    state = new_state(args.task.strip(), args.complexity, args.strategy, args.requirement, project_dir)
    save_state(state)
    print("workflow started in %s" % paths["state"])
    print_header(state)
    print("")
    print("next: %s" % _cmd("next", "--dir", project_dir))
    return 0


def cmd_next(args):
    state = load_state(args.dir)
    stage = current_stage(state)
    print_header(state)
    print("")
    if stage is None:
        print("all eleven stages are closed. Review the summary, then run:")
        print("  %s" % _cmd("complete", "--dir", args.dir))
        return 0
    print("now: %s" % stage)
    print("  %s." % STAGE_GUIDE[stage])
    print("close it: %s" % _cmd("update", stage, "--state done --note \"...\"", "--dir", args.dir))
    for note in warn(state):
        print(note)
    return 0


def cmd_status(args):
    state = load_state(args.dir)
    print_header(state)
    print_lists(state)
    for name in STAGES:
        entry = state["stages"][name]
        mark = {"open": "-", "done": "done", "skip": "skip"}[entry["state"]]
        note = " (%s)" % entry["note"] if entry.get("note") else ""
        print("  %-9s %s%s" % (name, mark, note))
    for note in warn(state):
        print(note)
    return 0


def cmd_update(args):
    state = load_state(args.dir)
    if args.stage not in STAGES:
        raise WorkflowError("unknown stage '%s'. Stages: %s" % (args.stage, ", ".join(STAGES)))
    entry = state["stages"][args.stage]
    if entry["state"] != "open":
        raise WorkflowError(
            "stage '%s' is already closed (%s). The lifecycle never moves backward."
            % (args.stage, entry["state"])
        )
    if args.state == "skip":
        if not (args.note or "").strip():
            raise WorkflowError("skipping a stage requires --note stating why it does not apply")
        if args.stage in CORE_STAGES[state["complexity"]]:
            print("note: '%s' is a core stage for a %s task; the skip is recorded in the state."
                  % (args.stage, state["complexity"]))
        entry["state"] = "skip"
    else:
        entry["state"] = "done"
    entry["note"] = (args.note or "").strip() or None
    if args.stage == "select" and args.strategy:
        data = load_strategies()
        strategy_by_id(data, args.strategy)
        state["strategy"] = args.strategy
        state["decisions"].append({
            "choice": "strategy: %s" % args.strategy,
            "reason": (args.note or "").strip() or "selected at the select stage",
            "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
        })
    save_state(state)
    nxt = current_stage(state)
    print("%s closed (%s). %s" % (args.stage, entry["state"],
                                  "next: %s" % nxt if nxt else "all stages closed; run complete"))
    return 0


def cmd_finding(args):
    state = load_state(args.dir)
    if args.kind not in FINDING_KINDS:
        raise WorkflowError("--kind must be one of: %s" % ", ".join(FINDING_KINDS))
    guard_text("finding", args.text)
    guard_text("evidence", args.evidence)
    state["findings"].append({
        "kind": args.kind,
        "text": args.text.strip(),
        "evidence": (args.evidence or "").strip() or None,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    if args.kind == "requirement":
        state["requirements"].append(args.text.strip())
    save_state(state)
    print("recorded %s finding #%d" % (args.kind, len(state["findings"])))
    return 0


def cmd_decision(args):
    state = load_state(args.dir)
    guard_text("decision", args.choice)
    guard_text("reason", args.reason)
    if not args.reason.strip():
        raise WorkflowError("a decision needs --reason; unexplained choices are not decisions")
    state["decisions"].append({
        "choice": args.choice.strip(),
        "reason": args.reason.strip(),
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    save_state(state)
    print("recorded decision #%d" % len(state["decisions"]))
    return 0


def cmd_verify(args):
    state = load_state(args.dir)
    if args.result not in VERIFY_RESULTS:
        raise WorkflowError("--result must be one of: %s" % ", ".join(VERIFY_RESULTS))
    guard_text("command", args.command)
    guard_text("notes", args.notes)
    state["verifications"].append({
        "command": args.command.strip(),
        "result": args.result,
        "notes": (args.notes or "").strip() or None,
        "time": time.strftime("%Y-%m-%dT%H:%M:%S"),
    })
    save_state(state)
    print("recorded verification #%d (%s)" % (len(state["verifications"]), args.result))
    return 0


def cmd_file(args):
    state = load_state(args.dir)
    path = args.path
    if args.remove:
        norm = path.replace(os.sep, "/")
        if norm not in state["files_changed"]:
            raise WorkflowError("'%s' is not in the recorded files" % norm)
        state["files_changed"] = [f for f in state["files_changed"] if f != norm]
        save_state(state)
        print("removed %s" % norm)
        return 0
    if not path.strip():
        raise WorkflowError("file path must not be empty")
    norm = path.strip().replace(os.sep, "/")
    guard_text("file path", norm)
    if norm not in state["files_changed"]:
        state["files_changed"].append(norm)
    save_state(state)
    print("tracked %s (%d file(s))" % (norm, len(state["files_changed"])))
    return 0


def _list_item_command(state, args, field, verb, done_flag, remove_flag):
    items = state[field]
    if args.text is not None:
        guard_text(field, args.text)
        items.append({"text": args.text.strip(), "done": False, "time": time.strftime("%Y-%m-%dT%H:%M:%S")})
        save_state(state)
        print("recorded %s #%d" % (verb, len(items)))
        return 0
    target = getattr(args, done_flag)
    if target is not None:
        if target < 1 or target > len(items):
            raise WorkflowError("%s #%d does not exist (1..%d)" % (verb, target, max(len(items), 1)))
        items[target - 1]["done"] = True
        save_state(state)
        print("%s #%d closed" % (verb, target))
        return 0
    raise WorkflowError("give the %s text to add one, or --done N to close one" % verb)


def cmd_milestone(args):
    state = load_state(args.dir)
    return _list_item_command(state, args, "milestones", "milestone", "done", None)


def cmd_remaining(args):
    state = load_state(args.dir)
    return _list_item_command(state, args, "remaining", "remaining item", "done", None)


def cmd_blocker(args):
    state = load_state(args.dir)
    if args.text is not None:
        guard_text("blocker", args.text)
        state["blockers"].append({"text": args.text.strip(), "resolved": False,
                                  "time": time.strftime("%Y-%m-%dT%H:%M:%S")})
        save_state(state)
        print("recorded blocker #%d" % len(state["blockers"]))
        return 0
    if args.resolve is not None:
        if args.resolve < 1 or args.resolve > len(state["blockers"]):
            raise WorkflowError("blocker #%d does not exist (1..%d)" % (args.resolve, max(len(state["blockers"]), 1)))
        state["blockers"][args.resolve - 1]["resolved"] = True
        save_state(state)
        print("blocker #%d resolved" % args.resolve)
        return 0
    raise WorkflowError("give the blocker text to add one, or --resolve N to resolve one")


def cmd_resume(args):
    state = load_state(args.dir)
    if args.json:
        print(json.dumps({
            "task": state["task"],
            "complexity": state["complexity"],
            "strategy": state["strategy"],
            "stage": current_stage(state),
            "requirements": state["requirements"],
            "findings": state["findings"],
            "decisions": state["decisions"],
            "files_changed": state["files_changed"],
            "verifications": state["verifications"],
            "milestones": state["milestones"],
            "remaining": [r for r in state["remaining"] if not r["done"]],
            "blockers": [b for b in state["blockers"] if not b["resolved"]],
        }, indent=1))
        return 0
    print("resuming after a context loss. The state is a claim, the repository is the truth:")
    print_header(state)
    print_lists(state)
    if state["requirements"]:
        print("requirements:")
        for r in state["requirements"]:
            print("  - %s" % r)
    if state["decisions"]:
        print("decisions so far:")
        for d in state["decisions"]:
            print("  - %s: %s" % (d["choice"], d["reason"]))
    print("")
    print("1. Check the current git branch and working tree; the user's uncommitted work outranks this state.")
    print("2. Re-open the recorded files and confirm the recorded findings still hold.")
    print("3. Re-run any verification whose result you cannot trust:")
    for v in state["verifications"]:
        print("   [%s] %s" % (v["result"], v["command"]))
    print("4. Do not repeat completed stages. Continue from the stage below.")
    stage = current_stage(state)
    if stage:
        print("   continue from: %s" % stage)
    else:
        print("   all stages closed: review, then complete")
    for note in warn(state):
        print(note)
    print("")
    print("next: %s" % _cmd("next", "--dir", args.dir))
    return 0


def cmd_complete(args):
    state = load_state(args.dir)
    open_blockers = [b for b in state["blockers"] if not b["resolved"]]
    if open_blockers and not args.force:
        for b in open_blockers:
            print("open blocker: %s" % b["text"])
        raise WorkflowError(
            "%d blocker(s) are still open. Resolve them or run complete --force to archive anyway."
            % len(open_blockers)
        )
    paths = state_paths(args.dir)
    archived = archive_state(state, args.dir)
    print("workflow complete. Archived to %s" % archived)
    print("")
    print("task: %s" % state["task"])
    print("what changed:")
    for f in state["files_changed"]:
        print("  - %s" % f)
    if not state["files_changed"]:
        print("  - (no files recorded)")
    print("why (decisions):")
    for d in state["decisions"]:
        print("  - %s: %s" % (d["choice"], d["reason"]))
    print("verified:")
    for v in state["verifications"]:
        print("  - [%s] %s" % (v["result"], v["command"]))
    if not state["verifications"]:
        print("  - (nothing was recorded as verified)")
    open_items = [r["text"] for r in state["remaining"] if not r["done"]]
    if open_blockers:
        print("limitation: %d blocker(s) were open at completion (--force):" % len(open_blockers))
        for b in open_blockers:
            print("  - %s" % b["text"])
    if open_items:
        print("remaining work:")
        for r in open_items:
            print("  - %s" % r)
    print("")
    print("Hand this summary to the user. Never commit, push or deploy on your own.")
    return 0


def _dimension_flag(name):
    return "--" + name.replace("_", "-")


def cmd_score(args):
    data = load_strategies()
    given = {}
    for dim in RUBRIC_DIMENSIONS:
        value = getattr(args, dim)
        if value is None:
            continue
        if not 0 <= value <= 10:
            raise WorkflowError("%s must be between 0 and 10, got %s" % (_dimension_flag(dim), value))
        given[dim] = float(value)
    if not given:
        raise WorkflowError(
            "score at least one dimension, e.g. %s 8" % _dimension_flag(RUBRIC_DIMENSIONS[0])
        )
    weights = dict(effective_weights(data, args.strategy))
    covered = sum(weights[d] for d in given)
    # Renormalize to the covered share of the rubric, so scoring 6 honest dimensions
    # of a complex change still lands on the same 0-100 scale as a full review.
    total = sum(given[d] * weights[d] for d in given) / covered * 10.0
    print("scores over %d of %d dimensions (weights cover %.0f%% of the rubric)%s"
          % (len(given), len(RUBRIC_DIMENSIONS), covered,
             ", strategy '%s'" % args.strategy if args.strategy else ""))
    for dim in RUBRIC_DIMENSIONS:
        if dim in given:
            print("  %-26s %4.1f / 10  (weight %.1f)" % (dim, given[dim], weights[dim]))
    print("weighted total: %.1f / 100" % total)
    weakest = sorted(given, key=lambda d: (given[d], -weights[d]))[:3]
    print("weakest signals: %s" % ", ".join("%s (%.0f/10)" % (d, given[d]) for d in weakest))
    if args.fatal:
        print("FATAL: a verified flaw makes this change wrong or unusable. It cannot ship as is, "
              "whatever the total says. Fix the flaw and score again.")
    elif total < 50:
        print("below the acceptable line for tracked work. Fix the weakest dimensions or record "
              "the trade-off as a decision.")
    return 0


def cmd_strategies(args):
    data = load_strategies()
    if args.strategy_id:
        s = strategy_by_id(data, args.strategy_id)
        if args.json:
            print(json.dumps(s, indent=1))
            return 0
        print("%s - %s (min complexity: %s)" % (s["id"], s["name"], s["min_complexity"]))
        print("matches: %s" % s["matches"])
        print("when: %s" % " | ".join(s["when"]))
        for stage, focus in sorted((s.get("stage_focus") or {}).items()):
            print("%s: %s" % (stage, focus))
        for check in s.get("verify", []):
            print("verify: %s" % check)
        emphasis = s.get("rubric_emphasis") or {}
        if emphasis:
            print("rubric emphasis: %s" % ", ".join("%s x%s" % (k, v) for k, v in sorted(emphasis.items())))
        return 0
    if args.json:
        print(json.dumps(data, indent=1))
        return 0
    for s in data["strategies"]:
        print("%-28s %-6s %s" % (s["id"], s["min_complexity"], s["name"]))
    return 0


def cmd_validate(args):
    load_strategies()
    weights = effective_weights(load_strategies())
    total = sum(w for _, w in weights)
    if abs(total - 100.0) > 0.01:
        raise WorkflowError("rubric weights sum to %.2f, not 100" % total)
    if args.project:
        paths = state_paths(args.project)
        if os.path.isfile(paths["state"]):
            _validate_state(_read_json(paths["state"]), paths["state"])
            print("state in %s is valid" % args.project)
    with open(RUBRIC_PATH, encoding="utf-8") as fh:
        rubric = fh.read()
    if not rubric.strip():
        raise WorkflowError("rubric.md is empty")
    print("strategies.json and rubric.md are valid; default weights sum to %d" % round(total))
    return 0


def cmd_recover(args):
    paths = state_paths(args.dir)
    path = paths["state"]
    if not os.path.isfile(path):
        raise WorkflowError("there is no %s to recover" % path)
    try:
        _read_json(path)
    except (OSError, ValueError):
        pass
    else:
        raise WorkflowError("%s parses fine; there is nothing to recover. Inspect it with status." % path)
    quarantine = path + ".corrupt-%s" % time.strftime("%Y%m%d-%H%M%S")
    os.replace(path, quarantine)
    print("quarantined the corrupted state to %s" % quarantine)
    print("you can now start a fresh workflow with init. The old file was kept, not deleted.")
    return 0


# ---------------------------------------------------------------- CLI

def _build_parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", default=".", help="project directory that owns the state (default: current)")
    parser = argparse.ArgumentParser(prog="workflow.py", description="CES task state engine")
    sub = parser.add_subparsers(dest="command")

    p = sub.add_parser("plan", parents=[common], help="preview the lifecycle for a complexity class")
    p.add_argument("--complexity", choices=COMPLEXITIES, required=True)
    p.add_argument("--strategy")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("init", parents=[common], help="start tracking a medium or complex task")
    p.add_argument("--task", required=True)
    p.add_argument("--complexity", choices=COMPLEXITIES, required=True)
    p.add_argument("--strategy")
    p.add_argument("--requirement", action="append")
    p.add_argument("--force", action="store_true", help="archive any active workflow and start a new one")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("next", parents=[common], help="what to do now")
    p.set_defaults(func=cmd_next)

    p = sub.add_parser("status", parents=[common], help="full state summary")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("update", parents=[common], help="close a lifecycle stage")
    p.add_argument("stage", choices=STAGES)
    p.add_argument("--state", choices=("done", "skip"), default="done")
    p.add_argument("--note")
    p.add_argument("--strategy", help="with 'update select', record the chosen strategy")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("finding", parents=[common], help="record a requirement, evidence or observation")
    p.add_argument("text")
    p.add_argument("--evidence")
    p.add_argument("--kind", default="observation")
    p.set_defaults(func=cmd_finding)

    p = sub.add_parser("decision", parents=[common], help="record a choice and its reason")
    p.add_argument("choice")
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_decision)

    p = sub.add_parser("verify", parents=[common], help="record a real verification result")
    p.add_argument("command")
    p.add_argument("--result", required=True, choices=VERIFY_RESULTS)
    p.add_argument("--notes")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("file", parents=[common], help="track (or --remove) a file the task touched")
    p.add_argument("path")
    p.add_argument("--remove", action="store_true")
    p.set_defaults(func=cmd_file)

    p = sub.add_parser("milestone", parents=[common], help="add a milestone, or close one with --done N")
    p.add_argument("text", nargs="?")
    p.add_argument("--done", type=int)
    p.set_defaults(func=cmd_milestone)

    p = sub.add_parser("remaining", parents=[common], help="add outstanding work, or close it with --done N")
    p.add_argument("text", nargs="?")
    p.add_argument("--done", type=int)
    p.set_defaults(func=cmd_remaining)

    p = sub.add_parser("blocker", parents=[common], help="add a blocker, or clear one with --resolve N")
    p.add_argument("text", nargs="?")
    p.add_argument("--resolve", type=int)
    p.set_defaults(func=cmd_blocker)

    p = sub.add_parser("resume", parents=[common], help="reorientation protocol after a context loss")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("complete", parents=[common], help="archive the workflow and print the report skeleton")
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=cmd_complete)

    p = sub.add_parser("score", parents=[common], help="apply the rubric weights from rubric.md")
    p.add_argument("--strategy")
    p.add_argument("--fatal", action="store_true")
    for dim in RUBRIC_DIMENSIONS:
        p.add_argument(_dimension_flag(dim), type=float)
    p.set_defaults(func=cmd_score)

    p = sub.add_parser("strategies", parents=[common], help="list strategies, or show one in detail")
    p.add_argument("strategy_id", nargs="?")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_strategies)

    p = sub.add_parser("validate", parents=[common], help="validate the skill's configuration files")
    p.add_argument("--project", help="also validate the state file of this project directory")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("recover", parents=[common], help="quarantine a corrupted state file")
    p.set_defaults(func=cmd_recover)

    return parser


def main(argv=None):
    parser = _build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 2
    try:
        return args.func(args)
    except WorkflowError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    except BrokenPipeError:
        # Output was piped into a consumer that closed early (e.g. `| head`).
        try:
            sys.stdout.close()
        except Exception:
            pass
        return 0


if __name__ == "__main__":
    sys.exit(main())
