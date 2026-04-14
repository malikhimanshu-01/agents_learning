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


# ─── Human approval node (uses interrupt to pause for Chainlit) ──────────────

def human_approval_node(state: ArchitectState) -> dict:
    """Pause pipeline and wait for human decision via Chainlit action button."""
    architecture = state.get("architecture", {})
    evaluation = state.get("evaluation", {})

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


# ─── Conditional routing functions ───────────────────────────────────────────

def route_after_evaluation(state: ArchitectState) -> str:
    """Route to redesigner (if loops remain) or human_approval."""
    evaluation = state.get("evaluation", {})
    passed = evaluation.get("passed", False)
    loop_count = state.get("loop_count", 0)
    max_loops = state.get("max_loops", 3)

    if passed:
        return "human_approval"
    elif loop_count < max_loops:
        return "redesigner"
    else:
        return "human_approval"


def route_after_approval(state: ArchitectState) -> str:
    """Route to ARM generator or END based on human decision."""
    if state.get("human_approved"):
        return "arm_generator"
    return END


# ─── Build the graph ─────────────────────────────────────────────────────────

builder = StateGraph(ArchitectState)

# Register nodes
builder.add_node("planner", planner_agent)
builder.add_node("architect", architect_agent)
builder.add_node("evaluator", evaluator_agent)
builder.add_node("redesigner", redesigner_agent)
builder.add_node("human_approval", human_approval_node)
builder.add_node("arm_generator", arm_generator_agent)

# Entry point
builder.set_entry_point("planner")

# Linear edges
builder.add_edge("planner", "architect")
builder.add_edge("architect", "evaluator")

# Conditional: after evaluation → redesigner (loop) OR human_approval
builder.add_conditional_edges(
    "evaluator",
    route_after_evaluation,
    {
        "human_approval": "human_approval",
        "redesigner": "redesigner",
    },
)

# Redesign loop: redesigner → architect (cycle)
builder.add_edge("redesigner", "architect")

# Conditional: after human approval → ARM generator OR END
builder.add_conditional_edges(
    "human_approval",
    route_after_approval,
    {
        "arm_generator": "arm_generator",
        END: END,
    },
)

# Final edge
builder.add_edge("arm_generator", END)

# Compile with MemorySaver checkpointer (enables interrupt/resume)
memory = MemorySaver()
pipeline = builder.compile(checkpointer=memory)


if __name__ == "__main__":
    print("Graph compiled successfully.")
    print(f"Nodes: {list(pipeline.nodes.keys())}")
