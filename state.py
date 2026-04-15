from typing import TypedDict, Optional


class ArchitectState(TypedDict):
    user_input: str
    plan: dict
    requirements_gaps: list[dict]   # gaps detected by planner: [{category, gap, assumption, impact}]
    gap_confirmed: Optional[bool]   # True = user confirmed gaps, False = re-run planner
    architecture: dict
    architecture_history: list[dict]  # snapshot per loop: [{loop, label, name, cost, confidence, complexity, redesign_notes}]
    evaluation: dict
    security_audit: dict              # output of security_auditor_agent: grade, findings, zero_trust_score
    loop_count: int
    max_loops: int
    human_approved: Optional[bool]
    arm_template: dict
    current_stage: str
    errors: list[str]
