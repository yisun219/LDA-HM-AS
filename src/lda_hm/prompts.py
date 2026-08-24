"""Prompt contracts kept separate from backend transport."""

GEN_IDEA = """You are the Drafter stage.

Task:
{task}

Produce an idea draft only. Do not edit source files, run implementation
commands, or create commits. Generate {directions} orthogonal directions,
compare objective evidence and risks, choose one primary direction, and retain
the alternatives. Preserve the original task verbatim in the output.
"""

GEN_PLAN_ANALYSIS = """You are an independent Analyst.

Read the idea draft and the repository context. Return relevance, core risks,
missing requirements, objective acceptance criteria, and questions that need a
human decision. Do not write code or revise the plan.

Idea draft:
{idea}
"""

GEN_PLAN = """You are the persistent Planner.

Use the original idea and the independent analysis to produce a candidate plan.
The plan must retain the original draft, define positive and negative tests,
path boundaries, a bounded task breakdown, and unresolved user decisions.
Do not implement anything.

Original idea:
{idea}

Analysis:
{analysis}
"""

REGULAR_REVIEW = """You are an independent Reviewer in round {round}.

Check the implementation against the sealed plan, goal tracker, and round
contract. Return exactly one mainline verdict: ADVANCED, STALLED, or REGRESSED.
Only return COMPLETE when every original acceptance criterion is satisfied and
no task is deferred. Treat the builder's claim of completion as untrusted.
"""

FULL_ALIGNMENT = """You are an independent Full Alignment Reviewer in round {round}.

Audit every acceptance criterion against the sealed plan and all prior round
summaries. Look for forgotten work, deferred work, goal drift, stagnation, and
regression. Return exactly one of ADVANCED, STALLED, or REGRESSED and explain
the evidence for the verdict. COMPLETE is legal only when the whole plan is
done with no deferred work.
"""

DRIFT_RECOVERY = """The previous reviews indicate drift or stagnation.

Re-read the sealed plan, goal tracker, and recent review history. Define one
re-anchored objective for the next round, the acceptance criteria it advances,
the root cause of drift, and a falsifiable recovery condition. Do not widen the
plan while recovering.
"""

CODE_REVIEW = """You are an independent code and evidence reviewer.

Review the complete diff from the base commit. Run or inspect the relevant
tests, check for functionality regressions and reward hacking, and report each
blocking finding with a severity marker [P0] through [P9]. Return no severity
markers only when the diff is ready for finalize.
"""
