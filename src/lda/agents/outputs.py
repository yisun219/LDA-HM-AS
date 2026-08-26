from __future__ import annotations

from typing import Any


BASE_OBJECT = {"type": "object", "additionalProperties": False}

SCHEMAS: dict[str, dict[str, Any]] = {
    "manager_action": {
        **BASE_OBJECT,
        "required": ["action", "target_id", "evidence_refs", "expected_value", "estimated_cost",
                     "risk", "reason_summary", "requested_budget", "preconditions"],
        "properties": {
            "action": {"enum": ["CREATE_MISSION", "REPRIORITIZE_MISSION", "PAUSE_MISSION",
                                "RESUME_MISSION", "STOP_MISSION", "CONTINUE_CANDIDATE",
                                "CREATE_RESEARCH_SNAPSHOT", "PROPOSE_CAPABILITY",
                                "START_CAPABILITY_MISSION", "RUN_PORTFOLIO_E2E", "PROPOSE_STOP"]},
            "target_id": {"type": ["string", "null"]},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "expected_value": {"type": "number", "minimum": 0},
            "estimated_cost": {"type": "number", "minimum": 0},
            "risk": {"type": "number", "minimum": 0, "maximum": 1},
            "reason_summary": {"type": "string"},
            "requested_budget": {"type": "object", "additionalProperties": False,
                                 "required": ["tokens", "sandbox_seconds", "cost"],
                                 "properties": {"tokens": {"type": "integer", "minimum": 0},
                                                "sandbox_seconds": {"type": "integer", "minimum": 0},
                                                "cost": {"type": "number", "minimum": 0}}},
            "preconditions": {"type": "array", "items": {"type": "string"}},
        },
    },
    "world_summary": {
        **BASE_OBJECT,
        "required": ["fact_refs", "active_missions", "budget_summary", "open_risks"],
        "properties": {
            "fact_refs": {"type": "array", "items": {"type": "string"}},
            "active_missions": {"type": "array", "items": {"type": "string"}},
            "budget_summary": {"type": "string"},
            "open_risks": {"type": "array", "items": {"type": "string"}},
        },
    },
    "mission_plan": {
        **BASE_OBJECT,
        "required": ["hypothesis", "profile_targets", "candidate_plan", "risk_controls"],
        "properties": {
            "hypothesis": {"type": "string"},
            "profile_targets": {"type": "array", "items": {"type": "string"}},
            "candidate_plan": {"type": "array", "items": {"type": "string"}},
            "risk_controls": {"type": "array", "items": {"type": "string"}},
        },
    },
    "builder_candidate": {
        **BASE_OBJECT,
        "required": ["hypothesis", "cflags", "cxxflags", "expected_effect", "evidence_refs"],
        "properties": {
            "hypothesis": {"type": "string"},
            "cflags": {"type": "array", "items": {"type": "string"}},
            "cxxflags": {"type": "array", "items": {"type": "string"}},
            "expected_effect": {"type": "string"},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
        },
    },
    "review": {
        **BASE_OBJECT,
        "required": ["verdict", "findings", "required_actions", "evidence_refs"],
        "properties": {
            "verdict": {"enum": ["APPROVE", "REJECT", "REVISE"]},
            "findings": {"type": "array", "items": {"type": "string"}},
            "required_actions": {"type": "array", "items": {"type": "string"}},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
        },
    },
    "outcome": {
        **BASE_OBJECT,
        "required": ["classification", "evidence_refs", "root_cause_category", "reusable_lessons",
                     "mission_policy_updates", "capability_gap", "confidence"],
        "properties": {
            "classification": {"enum": ["SUCCESS_LOCAL", "SUCCESS_SYSTEM", "ABI_FAILURE",
                                          "FUNCTIONAL_FAILURE", "BENCHMARK_INVALID", "MICRO_NO_GAIN",
                                          "E2E_DILUTION", "E2E_REGRESSION", "BUILD_FAILURE",
                                          "CAPABILITY_GAP", "NO_OPTIMIZATION_SPACE", "BUDGET_EXHAUSTED"]},
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "root_cause_category": {"type": "string"},
            "reusable_lessons": {"type": "array", "items": {"type": "string"}},
            "mission_policy_updates": {"type": "array", "items": {"type": "string"}},
            "capability_gap": {"anyOf": [
                {"type": "object", "additionalProperties": False,
                 "required": ["kind", "scope", "reason"],
                 "properties": {"kind": {"type": "string"},
                                "scope": {"type": "array", "items": {"type": "string"}},
                                "reason": {"type": "string"}}},
                {"type": "null"},
            ]},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        },
    },
}


ROLE_SCHEMAS = {
    "Argus Manager": "manager_action",
    "World State Summarizer": "world_summary",
    "Mission Planner": "mission_plan",
    "Builder": "builder_candidate",
    "Reviewer": "review",
    "Outcome Classifier": "outcome",
}


def schema_for(name: str) -> dict[str, Any]:
    try:
        return SCHEMAS[name]
    except KeyError as exc:
        raise ValueError(f"unknown agent output schema: {name}") from exc
