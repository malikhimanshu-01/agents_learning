import json
import re

from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

from prompts.planner import PLANNER_PROMPT
from state import ArchitectState
from config import AZURE_DEPLOYMENT, AZURE_API_VERSION, TOKENS_STANDARD

llm = AzureChatOpenAI(
    azure_deployment=AZURE_DEPLOYMENT,
    api_version=AZURE_API_VERSION,
    max_tokens=TOKENS_STANDARD,
)


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("quota", "billing", "insufficient", "rate limit", "429"))


def _extract_json(content: str) -> dict:
    content = content.strip()
    match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", content)
    if match:
        content = match.group(1)
    else:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            content = content[start : end + 1]
    return json.loads(content)


def planner_agent(state: ArchitectState) -> dict:
    try:
        # If the user provided a clarification, append it to the original input
        user_input = state["user_input"]
        messages = [
            SystemMessage(content=PLANNER_PROMPT),
            HumanMessage(content=f"User requirement:\n{user_input}"),
        ]
        response = llm.invoke(messages)
        plan = _extract_json(response.content)

        # Extract gaps from plan (planner now embeds them in the plan JSON)
        gaps = plan.pop("requirements_gaps", [])

        return {
            "plan": plan,
            "requirements_gaps": gaps,
            "gap_confirmed": False,          # reset — needs gap_review pass
            "current_stage": "gap_review",
            "errors": state.get("errors", []),
        }
    except json.JSONDecodeError as e:
        errors = list(state.get("errors", [])) + [f"Planner JSON parse error: {e}"]
        return {
            "plan": {
                "workload_type": "unknown", "scale": "medium", "regions": ["eastus"],
                "availability_requirement": "99.9%", "key_services": [],
                "constraints": {}, "non_functional": {},
            },
            "requirements_gaps": [],
            "gap_confirmed": True,           # skip review on parse error
            "current_stage": "architect",
            "errors": errors,
        }
    except Exception as e:
        if _is_quota_error(e):
            raise RuntimeError(
                "Azure OpenAI quota/rate limit hit. Check your deployment limits at "
                "portal.azure.com → Azure OpenAI → your resource → Deployments."
            ) from e
        errors = list(state.get("errors", [])) + [f"Planner error: {e}"]
        return {
            "plan": {}, "requirements_gaps": [], "gap_confirmed": True,
            "current_stage": "architect", "errors": errors,
        }
