import json
import re

from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

from prompts.arm_generator import ARM_PROMPT
from state import ArchitectState
from config import AZURE_DEPLOYMENT, AZURE_API_VERSION, TOKENS_ARM

llm = AzureChatOpenAI(
    azure_deployment=AZURE_DEPLOYMENT,
    api_version=AZURE_API_VERSION,
    max_tokens=TOKENS_ARM,
)


def _is_quota_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(k in msg for k in ("quota", "billing", "insufficient", "rate limit", "429"))


def _slim_architecture(arch: dict) -> dict:
    """
    Strip reasoning/display-only fields from the architecture before sending
    to the LLM. This significantly reduces input token usage, leaving more
    budget for the ARM template output.
    """
    drop_keys = {
        "why", "tradeoffs", "purpose", "redesign_notes",
        "alternative_variant", "comparison",
        "confidence_score", "confidence_reasoning",
        "deployment_complexity", "variant_label",
        "cost_breakdown",            # not needed for ARM resources
    }

    def _clean(obj):
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items() if k not in drop_keys}
        if isinstance(obj, list):
            return [_clean(i) for i in obj]
        return obj

    return _clean(arch)


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


def _repair_truncated_json(raw: str) -> dict | None:
    """
    If the LLM output was truncated mid-JSON, try to recover a partial but
    valid template by closing open arrays/objects.
    """
    # Find the outermost { ... }
    start = raw.find("{")
    if start == -1:
        return None
    fragment = raw[start:]

    # Try closing the JSON incrementally by appending bracket sequences
    closers = ["]}}", "]}", "}", "}}"]
    for tail in closers:
        try:
            return json.loads(fragment + tail)
        except json.JSONDecodeError:
            pass

    # Last resort: truncate to last complete resource object and close
    # Find last occurrence of "},\n    {" pattern — typical between resources
    last_comma = fragment.rfind("},\n    {")
    if last_comma != -1:
        trimmed = fragment[: last_comma + 1]  # keep up to and including the closing }
        for tail in ["\n  ]\n}", "\n]}"]:
            try:
                candidate = trimmed + tail
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass

    return None


def arm_generator_agent(state: ArchitectState) -> dict:
    architecture = state.get("architecture", {})
    plan         = state.get("plan", {})

    # Slim plan too — only the fields ARM cares about
    slim_plan = {
        "workload_type": plan.get("workload_type"),
        "regions":       plan.get("regions", []),
        "constraints":   plan.get("constraints", {}),
    }

    try:
        slim_arch = _slim_architecture(architecture)
        context = (
            f"Architecture (components, networking, security, DR, monitoring):\n"
            f"{json.dumps(slim_arch, indent=2)}\n\n"
            f"Requirements summary:\n{json.dumps(slim_plan, indent=2)}\n\n"
            "Generate the complete ARM template for ALL components listed above."
        )
        messages = [
            SystemMessage(content=ARM_PROMPT),
            HumanMessage(content=context),
        ]
        response = llm.invoke(messages)
        raw = response.content

        try:
            arm_template = _extract_json(raw)
        except json.JSONDecodeError as parse_err:
            # Try repair before giving up
            repaired = _repair_truncated_json(raw)
            if repaired and repaired.get("resources"):
                arm_template = repaired
                errors = list(state.get("errors", [])) + [
                    f"ARM template was truncated — recovered {len(repaired.get('resources', []))} resources"
                ]
                # Ensure schema fields
                arm_template.setdefault(
                    "$schema",
                    "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
                )
                arm_template.setdefault("contentVersion", "1.0.0.0")
                return {
                    "arm_template": arm_template,
                    "current_stage": "complete",
                    "errors": errors,
                }
            raise parse_err

        arm_template.setdefault(
            "$schema",
            "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
        )
        arm_template.setdefault("contentVersion", "1.0.0.0")

        return {
            "arm_template": arm_template,
            "current_stage": "complete",
            "errors": state.get("errors", []),
        }

    except json.JSONDecodeError as e:
        errors = list(state.get("errors", [])) + [f"ARM Generator JSON parse error: {e}"]
        fallback = {
            "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
            "contentVersion": "1.0.0.0",
            "parameters": {
                "environment": {"type": "string", "defaultValue": "prod"},
                "location":    {"type": "string", "defaultValue": "[resourceGroup().location]"},
                "namingPrefix": {"type": "string", "defaultValue": "azure-arch"},
            },
            "variables": {},
            "resources": [],
            "outputs": {},
            "_error": f"ARM template generation failed: {e}",
        }
        return {"arm_template": fallback, "current_stage": "complete", "errors": errors}

    except Exception as e:
        if _is_quota_error(e):
            raise RuntimeError(
                "Azure OpenAI quota/rate limit hit. Check your deployment limits at "
                "portal.azure.com → Azure OpenAI → your resource → Deployments."
            ) from e
        errors = list(state.get("errors", [])) + [f"ARM Generator error: {e}"]
        return {
            "arm_template": {
                "$schema": "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#",
                "contentVersion": "1.0.0.0",
                "parameters": {}, "variables": {}, "resources": [], "outputs": {},
                "_error": str(e),
            },
            "current_stage": "complete",
            "errors": errors,
        }
