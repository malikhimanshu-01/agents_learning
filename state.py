from typing import TypedDict, Optional


class ArchitectState(TypedDict):
    user_input: str
    plan: dict
    requirements_gaps: list[dict]   # gaps detected by planner: [{category, gap, assumption, impact}]
    gap_confirmed: Optional[bool]   # True = user confirmed gaps, False = re-run planner
    architecture: dict
    evaluation: dict
    loop_count: int
    max_loops: int
    human_approved: Optional[bool]
    arm_template: dict
    current_stage: str
    errors: list[str]
