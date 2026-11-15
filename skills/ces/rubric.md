# The CES engineering rubric

Every implementation CES produces is judged against this page. It is used three ways:
during **solution selection** (comparing candidate approaches), during **implementation
review** (stage evaluate), and during **final verification** (stage review). The `score`
command in `workflow.py` does the arithmetic; the weights here and the `RUBRIC_WEIGHTS`
table in `workflow.py` must stay identical, and the tests check that they do.

Do not score ceremony for trivial work. A one-line fix is judged by walking its two or
three relevant dimensions mentally, not by running the scorer.

## The twelve dimensions

Each dimension is scored 0 to 10. The weight is its share of the 100-point total.
A 10 means as good as this task realistically allows; a 7 means fit for purpose with
known, minor gaps; a 4 means a real problem a reviewer would raise; 0 means broken.

| dimension | weight | the question |
| --- | --- | --- |
| functional_correctness | 18 | Does it actually work? No logic errors, no false claims, no path that produces a wrong result. |
| requirement_completeness | 14 | Does it meet every requirement the task actually states, judged against the task text, not against taste? |
| root_cause_accuracy | 10 | For a fix: does it address the first real divergence between actual and expected behavior, or a symptom? |
| code_quality | 8 | Is the change clear, idiomatic for the codebase, free of debug leftovers, dead code and magic values? |
| maintainability | 8 | Can the next engineer extend and modify this without archaeology? Are names, structure and seams sane? |
| security | 8 | Are trust boundaries, secrets, untrusted input and authorization handled correctly? Nothing new exposed. |
| compatibility | 8 | Do existing callers, interfaces, data and environments keep working? Public contracts unchanged unless asked. |
| test_coverage | 8 | Do the relevant checks exist and run? Regression tests for real bugs, failure paths for new behavior? |
| performance | 6 | Are cost, load and resource use appropriate? No unbounded queries, loops, queues or memory growth. |
| error_handling | 6 | Do failures fail safely and loudly: bounded retries, real timeouts, honest errors, cleanup on the way out? |
| regression_risk | 4 | How likely is this change to break something it does not intend to touch? Smallest complete change wins. |
| implementation_complexity | 2 | Is the complexity right-sized? Simplest thing that fully does the job scores 10, bloat scores 0. |

Weighted total = sum of (score x weight) / 100. That gives a number from 0 to 100.

## Scale by task class

Risk sets the depth of evaluation, not ceremony:

- **Small:** walk correctness, completeness and regression risk mentally. Report honestly.
  No scores, no state file.
- **Medium:** score the six to eight dimensions that carry real risk for this change with
  the `score` command. A total of 50 with no fatal flag is the acceptable line; below it,
  fix the weakest dimensions or record the trade-off as a decision.
- **Complex:** score all twelve dimensions, ideally with the task's strategy emphasis
  applied. Weak dimensions get fixed or get a recorded reason. The final review repeats
  the walk over the actual diff.

## Strategy emphasis

`strategies.json` may carry a `rubric_emphasis` object per strategy: multipliers on the
default weights above (for example, bug investigation multiplies `root_cause_accuracy`
by 2.5 and `implementation_complexity` by 0.5). The `score --strategy <id>` command
applies the multipliers and renormalizes the total to 100, so emphasis shifts attention
without changing the scale. Multipliers never excuse a dimension that is genuinely broken.

## The fatal rule

Mark the change `fatal` only when you have verified a flaw that makes it wrong or unusable
for the task: code that cannot work, a broken data contract, a security hole with a real
path, the wrong problem solved. A fatal change cannot ship, whatever the total says. Say
what is fatal in plain words, fix it, and score again.

## What the rubric does not reward

- **Volume.** More code, more comments and more files are not quality. The smallest
  complete change that meets the requirements scores highest.
- **Confidence.** "This should work" is worth nothing. A verification command that ran and
  passed is worth everything.
- **Novelty.** Using the project's existing patterns beats importing a clever new one.
- **Self-praise.** The rubric scores the diff and the verified behavior, never the report
  about the diff.
- **Ceremony.** Plans, state files and scores exist to reduce risk, not to perform work.
  Proportionality is itself part of the score.
