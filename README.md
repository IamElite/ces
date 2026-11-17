# CES - Coding Expert System

**Version:** 3.0.0
**Type:** Agent Skill (multi-file)
**Runtime:** `SKILL.md` orchestrator + `workflow.py` engine + `strategies.json` + `rubric.md`

CES is an engineering lifecycle for coding agents. It takes a task from understanding
through classification, inspection, diagnosis, strategy selection, planning,
implementation, verification, rubric-based evaluation and a final diff review, and
reports honestly at the end. Small tasks stay small; complex tasks get milestones,
resumable state and scored quality gates.

## What it does

1. **Understand** the request and its constraints; never re-ask what was already given.
2. **Classify** the task small, medium or complex, and set the process weight accordingly.
3. **Inspect** the real project: instructions, entry points, callers, config, dependencies, git state.
4. **Diagnose** to the first confirmed divergence between actual and expected behavior.
5. **Select** a fitting strategy from seventeen catalog entries (bug investigation, database
   engineering, Telegram bots, media pipelines, scraping, deployment, security review, ...).
6. **Plan** milestones that each end in verifiable state - complex work only.
7. **Implement** the smallest complete change that fits the existing architecture.
8. **Verify** with real checks and record real results; nothing is claimed that did not run.
9. **Evaluate** the change against a twelve-dimension rubric, weighted by the chosen strategy.
10. **Review** the final diff for scope, secrets, regressions and accidental edits.
11. **Report** what changed, why, what was tested, what remains.

## Operational logging: owner visibility without spam

CES guides agents to add and preserve logs for meaningful user actions, task
transitions, important milestones, outcomes and failures. Logs should help an owner
understand what the application is doing without becoming a transcript of internal
execution.

- Record important actions with useful context, such as the actor and resource when
  appropriate.
- Log meaningful milestones for long-running operations, not every loop, chunk,
  polling cycle, progress tick or internal function call.
- Emit each event once at its natural ownership boundary; avoid duplicate messages
  from handlers, services and workers reporting the same action.
- Reuse the project's existing logger. Use `INFO` for meaningful activity,
  `SUCCESS` for successful operation outcomes, `WARNING` for recoverable issues,
  `ERROR` for failures and `DEBUG` for low-level diagnostics.
- Keep messages concise and actionable. Never expose credentials, tokens or sensitive
  personal data.

### Log message presentation

For new or revised application logs, CES specifies a compact, single-line format with
fixed-width timestamp and severity columns. Use a readable date and 12-hour time with
seconds, pad severity names so every event message starts at the same position, and
keep each event on one line. Do not use tree connectors, continuation blocks,
decorative borders or multi-line detail layouts.

Use event symbols consistently: `+` for a task added, `↓` for a download started,
`↑` for an upload started, `✓` for an operation completed, `✔` for a task completed,
`✗` for a failure, `!` for a warning, `»` for processing, `×` for cancellation,
`↻` for retry and `—` for an intentionally skipped item. Include useful context in
the same line only when it materially helps identify or understand the event.

The presentation rules are defined in detail in `skills/ces/SKILL.md`. They do not
require adding a logging framework or replacing a project's existing logger.

## Documentation stays in sync

The root README is the first stop for users. Every user-visible feature, bug fix or
change to behavior, commands, configuration, compatibility or workflows should update
this README in the same change, with a short explanation and a usage example when
helpful. Keep it accurate and user-focused; internal-only refactors do not need
documentation noise. Update a relevant feature guide as well when one exists.

## Architecture

Arena-inspired and deliberately multi-file. `SKILL.md` is the orchestrator; the
supporting components do real work:

```text
ces/
├── skills/
│   └── ces/
│       ├── SKILL.md          # the orchestrator: lifecycle, rules, playbooks
│       ├── workflow.py       # executable state engine (CLI, stdlib Python 3.8+)
│       ├── strategies.json   # 17 strategies: match signals, stage focus, verify checklists, rubric emphasis
│       └── rubric.md         # 12 weighted quality dimensions, anchors, fatal rule
├── tests/
│   └── test_workflow.py      # behavior tests: full lifecycle through the CLI, guards, integrity
├── .claude-plugin/
│   ├── plugin.json           # Claude Code plugin manifest
│   └── marketplace.json      # Claude Code marketplace entry
├── README.md
├── .gitignore
└── LICENSE
```

### `workflow.py` - the state engine

The deterministic memory for tracked work (medium and complex tasks; small tasks are
refused on purpose). All commands accept `--dir` (the project directory, default: the
current one). State lives in `.ces/workflow.json`, written atomically with a one-write
backup; a corrupted state is quarantined, never deleted; nothing is ever committed,
pushed or deployed by the tool.

```bash
python3 workflow.py plan --complexity complex            # preview the lifecycle, writes nothing
python3 workflow.py init --task "..." --complexity medium --strategy bug-investigation
python3 workflow.py next                                 # what to do now, with the exact command
python3 workflow.py status                               # full summary, stage by stage
python3 workflow.py update inspect --state done --note "..."
python3 workflow.py update select --state done --strategy telegram-bot-development
python3 workflow.py finding "..." --evidence "file.py:88" --kind evidence
python3 workflow.py decision "..." --reason "..."
python3 workflow.py verify "pytest tests/test_x.py" --result pass
python3 workflow.py file src/api.py        # file --remove src/api.py to untrack
python3 workflow.py milestone "..." / remaining "..." / blocker "..."
python3 workflow.py resume                 # recovery protocol after a context loss
python3 workflow.py score --strategy bug-investigation --functional-correctness 9 ...
python3 workflow.py strategies             # the catalog, or one entry in detail
python3 workflow.py complete               # archive and print the report skeleton
python3 workflow.py validate               # check the configuration files
```

The engine never stores credentials: text that looks like private key material is
refused, and the skill instructs agents to reference where a secret lives instead of
storing it.

### `strategies.json` - the strategy catalog

Seventeen strategies from `focused-change` to `complex-multi-stage`. Each entry says
what it matches, the signals that identify it, which lifecycle stages carry the
weight, a verification checklist, and `rubric_emphasis` multipliers that shift the
rubric weights when scoring with that strategy. Edit freely; run
`python3 workflow.py validate` after.

### `rubric.md` - the quality rubric

Twelve dimensions (functional correctness, requirement completeness, root-cause
accuracy, code quality, maintainability, security, compatibility, test coverage,
performance, error handling, regression risk, right-sized complexity), each scored 0-10
with weights summing to 100. The weights table is mirrored by `RUBRIC_WEIGHTS` in
`workflow.py`, and the tests check the two stay identical. Strategy emphasis
renormalizes the weights; the fatal rule stops delivery of a verified-broken change
whatever the total says.

## Install

### Fast project-local install (OpenCode)

Run this from the root of the project where you want CES installed:

```bash
npx skills add https://github.com/IamElite/ces/tree/dev/skills/ces --agent opencode --copy --yes
```

This installs the skill to `.agents/skills/ces/`. It fetches only the CES skill folder
(`SKILL.md`, `workflow.py`, `strategies.json`, and `rubric.md`) instead of cloning
the full repository with tests, plugin metadata and other development files.
`--yes` skips interactive confirmation and `--copy` creates a normal project copy.

For Codex, use the same command with `--agent codex`; its project skill path is also
`.agents/skills/`.

### Update later

From the same project root:

```bash
npx skills update ces --yes
```

### Claude Code plugin install

```text
/plugin marketplace add IamElite/ces
/plugin install ces@ces
```

### Manual install

Copy the complete `skills/ces/` directory into the agent's supported skill
directory. Keep all four files together because `workflow.py` loads
`strategies.json` and `rubric.md` from beside itself.

## Compatibility

- The engine needs Python 3.8 or newer, standard library only. No pip installs.
- The skill instructions are agent-agnostic (Agent Skills format): any host that can
  read files and run a shell can use CES. Claude Code additionally supports the
  plugin metadata above.
- `npx skills add` / `npx skills update` come from the vercel-labs skills CLI; verify
  current behavior with `npx skills --help` if your CLI version differs.

## Run the tests

```bash
python -m unittest discover -s tests -v
```

The suite drives a full complex-task lifecycle through the real command line and
covers the guards, state recovery, strategy catalog validity, rubric weight sync and
plugin metadata consistency.

## Version

3.0.0 - the Arena-inspired multi-file rebuild: eleven-stage lifecycle engine,
strategy catalog, engineering rubric, resumable state, plugin metadata and a
behavioral test suite. Previous releases: 2.0.0 (single-file skill), 1.x (modular
and compact five-file generations).

## License

MIT License. See [LICENSE](LICENSE).
