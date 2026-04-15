import json
import re

from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

from prompts.architect import ARCHITECT_PROMPT
from state import ArchitectState
from config import AZURE_DEPLOYMENT, AZURE_API_VERSION, TOKENS_LARGE

llm = AzureChatOpenAI(
    azure_deployment=AZURE_DEPLOYMENT,
    api_version=AZURE_API_VERSION,
    max_tokens=TOKENS_LARGE,
)


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("quota", "billing", "insufficient", "rate limit", "429"))


def _extract_json(content: str) -> dict:
    content = content.strip()
    match = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", content)
    if match:
        content = match.group(1)
    else:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            content = content[start : end + 1]
    return json.loads(content)


def architect_agent(state: ArchitectState) -> dict:
    plan = state.get("plan", {})
    loop_count = state.get("loop_count", 0)

    # Capture redesign_notes the redesigner embedded in the previous architecture
    # before we overwrite it with our new generation.
    prev_redesign_notes = state.get("architecture", {}).get("redesign_notes", [])

    try:
        user_context = (
            f"Requirements Plan:\n{json.dumps(plan, indent=2)}\n\n"
            f"Original Request:\n{state.get('user_input', '')}"
        )
        messages = [
            SystemMessage(content=ARCHITECT_PROMPT),
            HumanMessage(content=user_context),
        ]
        response = llm.invoke(messages)
        architecture = _extract_json(response.content)

        # ── Snapshot for architecture history ────────────────────────────────
        history = list(state.get("architecture_history", []))
        label = "Initial Design" if loop_count == 0 else f"Redesign Loop {loop_count}"
        history.append({
            "loop": loop_count,
            "label": label,
            "architecture_name": architecture.get("architecture_name", "Azure Solution"),
            "description": architecture.get("description", ""),
            "confidence_score": architecture.get("confidence_score"),
            "estimated_monthly_cost_usd": architecture.get("estimated_monthly_cost_usd", 0),
            "component_count": len(architecture.get("components", [])),
            "deployment_complexity": architecture.get("deployment_complexity", {}),
            "redesign_notes": prev_redesign_notes,  # what the redesigner changed to produce this version
        })

        return {
            "architecture": architecture,
            "architecture_history": history,
            "current_stage": "evaluator",
            "errors": state.get("errors", []),
        }
    except json.JSONDecodeError as e:
        errors = list(state.get("errors", [])) + [f"Architect JSON parse error: {e}"]
        return {
            "architecture": {
                "architecture_name": "Draft Azure Solution",
                "description": "Architecture could not be fully parsed.",
                "components": [], "networking": {}, "security": {},
                "disaster_recovery": {"rto_minutes": 60, "rpo_minutes": 30, "strategy": "Active-Passive"},
                "estimated_monthly_cost_usd": 0,
            },
            "architecture_history": state.get("architecture_history", []),
            "current_stage": "evaluator",
            "errors": errors,
        }
    except Exception as e:
        if _is_quota_error(e):
            raise RuntimeError(
                "Azure OpenAI quota/rate limit hit. Check your deployment limits at "
                "portal.azure.com → Azure OpenAI → your resource → Deployments."
            ) from e
        errors = list(state.get("errors", [])) + [f"Architect error: {e}"]
        return {
            "architecture": {},
            "architecture_history": state.get("architecture_history", []),
            "current_stage": "evaluator",
            "errors": errors,
        }
