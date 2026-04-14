from typing import TypedDict, Optional


class ArchitectState(TypedDict):
    user_input: str
    plan: dict
    architecture: dict
    evaluation: dict
    loop_count: int
    max_loops: int
    human_approved: Optional[bool]
    arm_template: dict
    current_stage: str
    errors: list[str]
