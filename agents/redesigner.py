import json
import re

from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

from prompts.redesigner import REDESIGNER_PROMPT
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


def redesigner_agent(state: ArchitectState) -> dict:
    architecture = state.get("architecture", {})
    evaluation = state.get("evaluation", {})
    loop_count = state.get("loop_count", 0)

    try:
        context = (
            f"Current Architecture:\n{json.dumps(architecture, indent=2)}\n\n"
            f"Evaluator Feedback:\n{json.dumps(evaluation, indent=2)}\n\n"
            f"This is redesign iteration {loop_count + 1}. "
            f"Focus on fixing these critical issues:\n"
            + "\n".join(f"- {issue}" for issue in evaluation.get("critical_issues", []))
        )
        messages = [
            SystemMessage(content=REDESIGNER_PROMPT),
            HumanMessage(content=context),
        ]
        response = llm.invoke(messages)
        new_architecture = _extract_json(response.content)
        return {
            "architecture": new_architecture,
            "loop_count": loop_count + 1,
            "current_stage": "architect",
            "errors": state.get("errors", []),
        }
    except json.JSONDecodeError as e:
        errors = list(state.get("errors", [])) + [f"Redesigner JSON parse error: {e}"]
        return {
            "architecture": architecture,
            "loop_count": loop_count + 1,
            "current_stage": "architect",
            "errors": errors,
        }
    except Exception as e:
        if _is_quota_error(e):
            raise RuntimeError(
                "Azure OpenAI quota/rate limit hit. Check your deployment limits at "
                "portal.azure.com → Azure OpenAI → your resource → Deployments."
            ) from e
        errors = list(state.get("errors", [])) + [f"Redesigner error: {e}"]
        return {
            "architecture": architecture,
            "loop_count": loop_count + 1,
            "current_stage": "architect",
            "errors": errors,
        }
