from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from lda_flow.benchmarks import summarize
from lda_flow.fence import source_allowlist, tree_digest
from lda_flow.models import Campaign
from lda_flow.priority import rank_missions
from lda_flow.trace import audit_trace

ROOT = Path(__file__).parents[1]


def test_campaign_is_strict_and_ranked():
    campaign = Campaign.from_yaml(str(ROOT / "campaigns/ubuntu2604-core-libs.yaml"))
    ranked = rank_missions(campaign.missions, campaign.weights)
    assert [item.mission.id for item in ranked] == ["libpng1-6", "libaio"]
    assert ranked[0].score > ranked[1].score


def test_hard_fences_cannot_be_disabled():
    campaign = Campaign.from_yaml(str(ROOT / "campaigns/ubuntu2604-core-libs.yaml"))
    assert campaign.missions[0].hard_fences.abi is True
    payload = campaign.model_dump()
    payload["missions"][0]["hard_fences"]["abi"] = False
    with pytest.raises(ValidationError):
        Campaign.model_validate(payload)


def test_benchmark_invalid_values_have_zero_reward():
    report = summarize(
        "x",
        (1.0, 1.0),
        (float("nan"), 1.0),
        lower_is_better=True,
        max_relative_mad=0.1,
        min_speedup=1.0,
    )
    assert report.reward == 0
    assert not report.passed


def test_source_allowlist_rejects_out_of_scope(tmp_path):
    (tmp_path / ".git").mkdir()
    import subprocess

    subprocess.run(["git", "-C", str(tmp_path), "init", "-q"], check=True)
    (tmp_path / "forbidden.txt").write_text("x")
    result = source_allowlist(tmp_path, ("src",), ())
    assert not result.passed


def test_trace_audit_ignores_prompt_text_but_catches_command(tmp_path):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps({"kind": "text", "text": "never use -march=native"})
        + "\n"
        + json.dumps({"kind": "tool", "command": "cc -march=native x.c"})
        + "\n"
    )
    findings = audit_trace(trace, (), ("-march=native",))
    assert len(findings) == 1


def test_trace_audit_catches_protected_recursive_delete(tmp_path):
    trace = tmp_path / "trace.jsonl"
    trace.write_text(
        json.dumps({"kind": "process", "command": "rm -rf benchmarks"}) + "\n"
    )
    findings = audit_trace(trace, ("benchmarks",), ())
    assert findings and "benchmarks" in findings[0].message


def test_tree_digest_changes_on_file_edit(tmp_path):
    (tmp_path / "x").write_text("a")
    before = tree_digest(tmp_path)
    (tmp_path / "x").write_text("b")
    assert before != tree_digest(tmp_path)
