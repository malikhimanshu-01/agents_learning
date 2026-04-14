from dotenv import load_dotenv

load_dotenv()

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt

from state import ArchitectState
from agents.planner import planner_agent
from agents.architect import architect_agent
from agents.evaluator import evaluator_agent
from agents.redesigner import redesigner_agent
from agents.arm_generator import arm_generator_agent


# ─── Gap Review node ─────────────────────────────────────────────────────────

def gap_review_node(state: ArchitectState) -> dict:
    """
    Pause after planning to show detected requirement gaps to the user.
    User can either confirm assumptions and proceed, or provide clarification
    which causes the planner to re-run with enriched input.
    """
    gaps = state.get("requirements_gaps", [])

    # If planner found no gaps, skip review entirely
    if not gaps:
        return {
            "gap_confirmed": True,
            "current_stage": "architect",
            "errors": state.get("errors", []),
        }

    result = interrupt(
        {
            "type": "gap_review",
            "gaps": gaps,
            "completeness_score": state.get("plan", {}).get("completeness_score", 100),
        }
    )

    # result is True → confirmed, or a non-empty string → user clarification
    if isinstance(result, str) and result.strip():
        # Merge clarification into original user_input so planner gets richer context
        clarification = result.strip()
        enriched_input = (
            state["user_input"]
            + f"\n\n--- User clarification (round {state.get('loop_count', 0) + 1}) ---\n"
            + clarification
        )
        return {
            "user_input": enriched_input,
            "gap_confirmed": False,
            "current_stage": "planner",
            "errors": state.get("errors", []),
        }

    return {
        "gap_confirmed": True,
        "current_stage": "architect",
        "errors": state.get("errors", []),
    }


# ─── Human approval node ─────────────────────────────────────────────────────

def human_approval_node(state: ArchitectState) -> dict:
    """Pause pipeline and wait for human decision via Chainlit action button."""
    architecture = state.get("architecture", {})
    evaluation   = state.get("evaluation", {})

    human_decision = interrupt(
        {
            "type": "human_approval",
            "architecture_name": architecture.get("architecture_name", "Azure Solution"),
            "overall_score": evaluation.get("overall_score", 0),
            "passed": evaluation.get("passed", False),
            "summary": evaluation.get("summary", ""),
        }
    )

    return {
        "human_approved": bool(human_decision),
        "current_stage": "arm_generator" if human_decision else "end",
        "errors": state.get("errors", []),
    }


# ─── Routing functions ────────────────────────────────────────────────────────

def route_after_gap_review(state: ArchitectState) -> str:
    """If user confirmed → architect. If clarification given → re-run planner."""
    return "architect" if state.get("gap_confirmed", True) else "planner"


def route_after_evaluation(state: ArchitectState) -> str:
    """Route to redesigner (if loops remain) or human_approval."""
    evaluation = state.get("evaluation", {})
    passed     = evaluation.get("passed", False)
    loop_count = state.get("loop_count", 0)
    max_loops  = state.get("max_loops", 3)

    if passed:
        return "human_approval"
    elif loop_count < max_loops:
        return "redesigner"
    else:
        return "human_approval"


def route_after_approval(state: ArchitectState) -> str:
    """Route to ARM generator or END based on human decision."""
    return "arm_generator" if state.get("human_approved") else END


# ─── Build graph ──────────────────────────────────────────────────────────────

builder = StateGraph(ArchitectState)

builder.add_node("planner",       planner_agent)
builder.add_node("gap_review",    gap_review_node)
builder.add_node("architect",     architect_agent)
builder.add_node("evaluator",     evaluator_agent)
builder.add_node("redesigner",    redesigner_agent)
builder.add_node("human_approval", human_approval_node)
builder.add_node("arm_generator", arm_generator_agent)

# Entry
builder.set_entry_point("planner")

# planner → gap_review (always)
builder.add_edge("planner", "gap_review")

# gap_review → architect (confirmed) OR planner (clarification provided)
builder.add_conditional_edges(
    "gap_review",
    route_after_gap_review,
    {"architect": "architect", "planner": "planner"},
)

# architect → evaluator
builder.add_edge("architect", "evaluator")

# evaluator → redesigner (loop) OR human_approval
builder.add_conditional_edges(
    "evaluator",
    route_after_evaluation,
    {"human_approval": "human_approval", "redesigner": "redesigner"},
)

# redesign loop back to architect
builder.add_edge("redesigner", "architect")

# human_approval → arm_generator OR END
builder.add_conditional_edges(
    "human_approval",
    route_after_approval,
    {"arm_generator": "arm_generator", END: END},
)

builder.add_edge("arm_generator", END)

memory   = MemorySaver()
pipeline = builder.compile(checkpointer=memory)


if __name__ == "__main__":
    print("Graph compiled successfully.")
    print(f"Nodes: {list(pipeline.nodes.keys())}")
