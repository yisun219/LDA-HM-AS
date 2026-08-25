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

GEN_PLAN_REVIEW = """You are a fresh independent Analyst.

Review the candidate plan against the complete original idea. Use the headings
AGREE, DISAGREE, REQUIRED_CHANGES, OPTIONAL_IMPROVEMENTS, and UNRESOLVED.
End with CONVERGED only when there are no required changes and no disagreement
that changes the work.

Original idea:
{idea}

Candidate plan:
{plan}
"""

GEN_PLAN_REVISE = """Revise the candidate plan using the independent review.

Preserve the original idea and all identifiers. Resolve every required change,
retain unresolved human decisions explicitly, and do not implement code.

Review:
{review}
"""

REGULAR_REVIEW = """You are an independent Reviewer in round {round}.

Check the implementation against the sealed plan, goal tracker, and round
contract. Read /opt/lda/review/candidate.patch,
/opt/lda/review/candidate-log.txt, and
/opt/lda/review/benchmark-summary.json. You are read-only and must not alter
the source or evidence. End with this exact protocol:
VERDICT: ADVANCED|STALLED|REGRESSED
BLOCKING: NONE
STATUS: COMPLETE|INCOMPLETE
Use one BLOCKING: line per blocking finding instead of BLOCKING: NONE. STATUS
may be COMPLETE only when every original acceptance criterion is satisfied,
the minimum benchmark targets are met, and no task is deferred. Treat the
builder's claim of completion as untrusted.
"""

FULL_ALIGNMENT = """You are an independent Full Alignment Reviewer in round {round}.

Audit every acceptance criterion against the sealed plan and all prior round
summaries plus /opt/lda/review/candidate.patch and benchmark-summary.json.
Look for forgotten work, deferred work, goal drift, stagnation, and
regression. Explain the evidence, then end with the same exact VERDICT,
BLOCKING, and STATUS protocol used by regular review. COMPLETE is legal only
when the whole plan is done, benchmark targets are met, and no work is deferred.
"""

DRIFT_RECOVERY = """The previous reviews indicate drift or stagnation.

Re-read the sealed plan, goal tracker, and recent review history. Define one
re-anchored objective for the next round, the acceptance criteria it advances,
the root cause of drift, and a falsifiable recovery condition. Do not widen the
plan while recovering.
"""

BUILDER_ROUND = """You are the persistent Builder for an Ubuntu package optimization round.

Before editing, read these immutable control artifacts:
- /opt/lda/control/task-card.json
- /opt/lda/control/plan.md
- /opt/lda/control/goal-tracker.md
- /opt/lda/control/baseline.json

You may modify only the Git repository at /opt/lda/work. Never modify or
replace /opt/lda/control, /opt/lda/baseline, /opt/lda/harness, test fixtures,
benchmark commands, fence commands, or prior evidence. Preserve ABI, FFI,
behavior, security defaults, and Debian package replacement compatibility.
Use the pinned Intel performance skills where relevant. Implement one bounded
mainline objective, run focused checks, and commit the result. Leave the
worktree clean. Do not weaken tests or manufacture benchmark evidence.

Round contract:
{contract}

End with a factual summary of changed files, the commit, tests run, remaining
risks, and whether this round advanced the sealed plan. A completion claim has
no authority; deterministic fences and a fresh Reviewer decide that.
"""

CODE_REVIEW = """You are an independent code and evidence reviewer.

Review /opt/lda/review/candidate.patch, candidate-log.txt, and
benchmark-summary.json against the immutable control artifacts. Inspect the
relevant source read-only, check for functionality regressions and reward
hacking, and report each blocking finding with a severity marker [P0] through
[P9]. Return no severity markers only when the diff is ready for finalize.
"""

METHODOLOGY_ANALYSIS = """You are a fresh independent methodology Analyst.

Read the immutable plan and goal tracker plus the completed run artifacts that
are available in /opt/lda/control and /opt/lda/review. Analyze which Builder
choices produced measured progress, which fences protected correctness, any
failed or misleading approaches, residual uncertainty, and reusable lessons.
Do not modify source or evidence. Return a concise methodology report grounded
in observed artifacts, not a generic success statement.
"""
