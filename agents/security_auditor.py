import json
import re

from dotenv import load_dotenv
from langchain_openai import AzureChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage

load_dotenv()

from prompts.security_auditor import SECURITY_AUDITOR_PROMPT
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
        end   = content.rfind("}")
        if start != -1 and end != -1:
            content = content[start : end + 1]
    return json.loads(content)


def _slim_architecture(arch: dict) -> dict:
    """Strip display-only fields before sending to security LLM."""
    drop = {
        "why", "tradeoffs", "purpose", "redesign_notes",
        "confidence_score", "confidence_reasoning",
        "deployment_complexity", "cost_breakdown",
        "alternative_variant", "comparison",
    }
    def _clean(obj):
        if isinstance(obj, dict):
            return {k: _clean(v) for k, v in obj.items() if k not in drop}
        if isinstance(obj, list):
            return [_clean(i) for i in obj]
        return obj
    return _clean(arch)


def security_auditor_agent(state: ArchitectState) -> dict:
    architecture = state.get("architecture", {})
    plan         = state.get("plan", {})
    loop_count   = state.get("loop_count", 0)

    slim_plan = {
        "workload_type":  plan.get("workload_type"),
        "compliance":     plan.get("constraints", {}).get("compliance", []),
        "scale":          plan.get("scale"),
        "availability":   plan.get("availability_requirement"),
        "non_functional": plan.get("non_functional", {}),
    }

    try:
        context = (
            f"Architecture to audit:\n{json.dumps(_slim_architecture(architecture), indent=2)}\n\n"
            f"Requirements context:\n{json.dumps(slim_plan, indent=2)}"
        )
        messages = [
            SystemMessage(content=SECURITY_AUDITOR_PROMPT),
            HumanMessage(content=context),
        ]
        response = llm.invoke(messages)
        audit    = _extract_json(response.content)

        # Normalise passed flag
        grade    = audit.get("security_grade", "C")
        audit["passed"] = bool(audit.get("passed", grade in ("A", "B")))

        # If security audit fails, inject critical findings into evaluation
        # so the redesigner knows exactly what security issues to fix.
        current_evaluation = state.get("evaluation", {})
        if not audit["passed"]:
            sec_issues = [
                f"[SECURITY {f.get('severity','').upper()}] {f.get('title','')}: {f.get('remediation','')}"
                for f in audit.get("critical_findings", [])
                if f.get("severity") in ("Critical", "High")
            ]
            if sec_issues:
                existing = current_evaluation.get("critical_issues", [])
                current_evaluation = {
                    **current_evaluation,
                    "critical_issues": sec_issues + existing,
                    "passed": False,
                }

        next_stage = (
            "human_approval"
            if audit["passed"]
            else ("redesigner" if loop_count < state.get("max_loops", 3) else "human_approval")
        )

        return {
            "security_audit": audit,
            "evaluation":     current_evaluation,
            "current_stage":  next_stage,
            "errors":         state.get("errors", []),
        }

    except json.JSONDecodeError as e:
        errors = list(state.get("errors", [])) + [f"Security Auditor JSON parse error: {e}"]
        fallback = {
            "security_grade": "C",
            "overall_score":  60,
            "passed":         False,
            "zero_trust_score": 50,
            "attack_surface_summary": "Audit could not be completed.",
            "critical_findings": [{"id": "SEC-ERR", "category": "Monitoring",
                                    "severity": "Medium", "title": "Audit parse error",
                                    "description": str(e), "affected_component": "—",
                                    "remediation": "Re-run security audit.", "azure_recommendation": ""}],
            "passed_checks": [],
            "compliance_notes": [],
            "recommendations": ["Re-run security audit"],
            "summary": "Security audit could not be completed due to a parsing error.",
        }
        return {
            "security_audit": fallback,
            "current_stage":  "human_approval",
            "errors":         errors,
        }

    except Exception as e:
        if _is_quota_error(e):
            raise RuntimeError(
                "Azure OpenAI quota/rate limit hit. Check your deployment limits at "
                "portal.azure.com → Azure OpenAI → your resource → Deployments."
            ) from e
        errors = list(state.get("errors", [])) + [f"Security Auditor error: {e}"]
        return {
            "security_audit": {
                "security_grade": "C", "overall_score": 0, "passed": False,
                "zero_trust_score": 0, "attack_surface_summary": str(e),
                "critical_findings": [], "passed_checks": [],
                "compliance_notes": [], "recommendations": [],
                "summary": f"Security audit failed: {e}",
            },
            "current_stage": "human_approval",
            "errors": errors,
        }
