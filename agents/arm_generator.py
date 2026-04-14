import json
import re

from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

from prompts.arm_generator import ARM_PROMPT
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


def arm_generator_agent(state: ArchitectState) -> dict:
    architecture = state.get("architecture", {})
    plan = state.get("plan", {})

    try:
        context = (
            f"Architecture to Convert to ARM Template:\n{json.dumps(architecture, indent=2)}\n\n"
            f"Requirements:\n{json.dumps(plan, indent=2)}\n\n"
            "Generate a complete, deployable ARM template for all components listed above. "
            "Use parameters for environment (dev/staging/prod), location, and namingPrefix. "
            "Add proper dependsOn chains and output all resource IDs."
        )
        messages = [
            SystemMessage(content=ARM_PROMPT),
            HumanMessage(content=context),
        ]
        response = llm.invoke(messages)
        arm_template = _extract_json(response.content)

        if "$schema" not in arm_template:
            arm_template["$schema"] = (
                "https://schema.management.azure.com/schemas/2019-04-01/deploymentTemplate.json#"
            )
        if "contentVersion" not in arm_template:
            arm_template["contentVersion"] = "1.0.0.0"

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
                "location": {"type": "string", "defaultValue": "[resourceGroup().location]"},
                "namingPrefix": {"type": "string", "defaultValue": "azure-arch"},
            },
            "variables": {}, "resources": [], "outputs": {},
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
