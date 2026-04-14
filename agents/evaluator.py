import json
import re

from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

from prompts.evaluator import EVALUATOR_PROMPT
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
    match = re.search(r"```(?:json)?\s*(\{[\s\S]*\})\s*```", content)
    if match:
        content = match.group(1)
    else:
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1:
            content = content[start : end + 1]
    return json.loads(content)


def evaluator_agent(state: ArchitectState) -> dict:
    architecture = state.get("architecture", {})
    plan = state.get("plan", {})
    try:
        context = (
            f"Architecture to Review:\n{json.dumps(architecture, indent=2)}\n\n"
            f"Original Requirements:\n{json.dumps(plan, indent=2)}"
        )
        messages = [
            SystemMessage(content=EVALUATOR_PROMPT),
            HumanMessage(content=context),
        ]
        response = llm.invoke(messages)
        evaluation = _extract_json(response.content)

        overall = evaluation.get("overall_score", 0)
        evaluation["passed"] = bool(evaluation.get("passed", overall >= 75))

        return {
            "evaluation": evaluation,
            "current_stage": "human_approval" if evaluation["passed"] else "redesigner",
            "errors": state.get("errors", []),
        }
    except json.JSONDecodeError as e:
        errors = list(state.get("errors", [])) + [f"Evaluator JSON parse error: {e}"]
        fallback_eval = {
            "scores": {"reliability": 50, "security": 50, "cost_optimization": 50,
                       "operational_excellence": 50, "performance_efficiency": 50},
            "overall_score": 50, "passed": False,
            "critical_issues": ["Evaluation could not be completed — JSON parse error"],
            "improvements": ["Re-run evaluation"], "strengths": [],
            "summary": "Evaluation failed due to a parsing error.",
        }
        return {"evaluation": fallback_eval, "current_stage": "redesigner", "errors": errors}
    except Exception as e:
        if _is_quota_error(e):
            raise RuntimeError(
                "Azure OpenAI quota/rate limit hit. Check your deployment limits at "
                "portal.azure.com → Azure OpenAI → your resource → Deployments."
            ) from e
        errors = list(state.get("errors", [])) + [f"Evaluator error: {e}"]
        return {
            "evaluation": {
                "passed": False, "overall_score": 0, "scores": {},
                "critical_issues": [str(e)], "improvements": [], "strengths": [],
                "summary": "Evaluation failed.",
            },
            "current_stage": "redesigner",
            "errors": errors,
        }
