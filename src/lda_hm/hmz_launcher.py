"""Start the LDA flow under the Humanize 2 runner with the E2B backend.

`bin/lda-hmz run <workspace>` is the production entry point: it builds the
two hmz agents (builder side / reviewer side, both executing inside the
card's sandbox through the relay backend) and hands them with the flow to
`hmz.runner.Runner`. The run is resumable: starting the same command again
picks the loop up from the state hmz kept.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="lda-hmz")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="run one card workspace under the hmz harness")
    run.add_argument("workspace", type=Path)
    run.add_argument("--run-id", default="")
    run.add_argument("--task", default="")
    run.add_argument("--contract", default="")
    run.add_argument(
        "--model",
        default=os.getenv("LDA_AGENT_MODEL", "claude-opus-4-8"),
        help="model for both sides (reviewer side overridable with LDA_AGENT_MODEL_REVIEWER)",
    )
    run.add_argument("--effort", default=os.getenv("LDA_AGENT_THINKING", "high"))
    check = sub.add_parser("check", help="verify the flow declaration without running agents")
    args = parser.parse_args(argv)

    flow_path = REPO / "flows" / "lda"
    if args.command == "check":
        from hmz.flows.driving import drives, resumes, wanted

        print("drives:", drives(flow_path))
        print("resumable:", resumes(flow_path))
        for place in wanted(flow_path):
            print("place:", place.name, "moments:", sorted(place.moments) or "none")
        return 0

    workspace = args.workspace.resolve()
    if not (workspace / ".lda-hm" / "task-card.json").is_file():
        print(f"lda-hmz: {workspace} has no installed task card", file=sys.stderr)
        return 2
    if args.run_id:
        os.environ["LDA_RUN_ID"] = args.run_id
    # The hmz cycle (kept state, traces) is keyed by the working directory:
    # running from the card workspace keeps every card's loop state and
    # trace lineage separate from every other card's.
    os.chdir(workspace)
    if args.task:
        os.environ["LDA_TASK"] = args.task
    if args.contract:
        os.environ["LDA_CONTRACT"] = args.contract
    os.environ.setdefault("PYTHONPATH", str(REPO / "src"))

    from hmz.agents import AgentConfig
    from hmz.runner import Runner

    from .hmz_backend import E2BHarnessAgent

    builder = E2BHarnessAgent(
        AgentConfig(model=args.model, effort=args.effort), name="builder"
    )
    reviewer = E2BHarnessAgent(
        AgentConfig(
            model=os.getenv("LDA_AGENT_MODEL_REVIEWER", args.model),
            effort=os.getenv("LDA_AGENT_THINKING_REVIEWER", args.effort),
        ),
        name="reviewer",
    )
    from .flow import InfrastructureOutage
    from .sandbox import SandboxUnavailable

    try:
        Runner(str(flow_path), [builder, reviewer]).run(str(workspace))
    except (InfrastructureOutage, SandboxUnavailable) as outage:
        # Temporary failure: the run state is saved; the driver loop resumes it.
        print(f"lda-hmz: paused on infrastructure outage: {outage}", file=sys.stderr)
        return 75
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
