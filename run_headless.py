"""
Headless runner for azure-architect-ai pipeline.
Runs the LangGraph pipeline directly without Chainlit, auto-approves human approval.
"""
import asyncio
import json
import uuid
import sys
import io

# Force UTF-8 output on Windows
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from dotenv import load_dotenv
load_dotenv()

from langgraph.types import Command
from graph import pipeline


PROMPT = (
    "A scalable AI chatbot web application for a startup expecting 10,000 daily active users, "
    "handling real-time conversations with low latency requirements (<200ms). The system should "
    "support session memory, API-based integration, and moderate traffic spikes. Requires 99.9% "
    "availability across East US region, no strict compliance requirements, and a cost-efficient "
    "budget (startup-friendly, prefer serverless and consumption-based pricing)."
)


def _fmt_plan(plan: dict) -> str:
    if not plan:
        return "  (no plan data)"
    lines = [
        f"  Workload Type : {plan.get('workload_type', 'N/A')}",
        f"  Scale         : {plan.get('scale', 'N/A')}",
        f"  Regions       : {', '.join(plan.get('regions', ['N/A']))}",
        f"  Availability  : {plan.get('availability_requirement', 'N/A')}",
        f"  Key Services  : {', '.join(plan.get('key_services', []))}",
    ]
    c = plan.get("constraints", {})
    if c.get("budget_usd_monthly"):
        lines.append(f"  Budget        : ${c['budget_usd_monthly']:,}/month")
    if c.get("compliance"):
        lines.append(f"  Compliance    : {', '.join(c['compliance'])}")
    return "\n".join(lines)


def _fmt_arch(arch: dict) -> str:
    if not arch:
        return "  (no architecture data)"
    lines = [
        f"  Name        : {arch.get('architecture_name', 'N/A')}",
        f"  Description : {arch.get('description', 'N/A')}",
        f"  Est. Cost   : ${arch.get('estimated_monthly_cost_usd', 0):,}/month",
        "",
        "  Components:",
    ]
    for i, c in enumerate(arch.get("components", []), 1):
        lines.append(
            f"    {i}. {c.get('name','?')} — {c.get('azure_service','?')} "
            f"[{c.get('sku','N/A')}] ({c.get('tier','?')}) — {c.get('purpose','?')}"
        )
    dr = arch.get("disaster_recovery", {})
    if dr:
        lines += [
            "",
            f"  DR: {dr.get('strategy','N/A')} | RTO {dr.get('rto_minutes','?')}min | RPO {dr.get('rpo_minutes','?')}min",
        ]
    return "\n".join(lines)


def _fmt_eval(ev: dict) -> str:
    if not ev:
        return "  (no evaluation data)"
    scores = ev.get("scores", {})
    status = "PASSED" if ev.get("passed") else "FAILED"
    lines = [
        f"  Status        : {status} (overall {ev.get('overall_score', 0)}/100)",
        f"  Reliability   : {scores.get('reliability', 0)}/100",
        f"  Security      : {scores.get('security', 0)}/100",
        f"  Cost Opt.     : {scores.get('cost_optimization', 0)}/100",
        f"  Ops Excellence: {scores.get('operational_excellence', 0)}/100",
        f"  Perf Eff.     : {scores.get('performance_efficiency', 0)}/100",
        f"  Summary       : {ev.get('summary', '')}",
    ]
    issues = ev.get("critical_issues", [])
    if issues:
        lines.append("  Critical Issues:")
        for issue in issues:
            lines.append(f"    - {issue}")
    strengths = ev.get("strengths", [])
    if strengths:
        lines.append("  Strengths:")
        for s in strengths[:5]:
            lines.append(f"    + {s}")
    return "\n".join(lines)


async def main():
    thread_id = str(uuid.uuid4())
    config = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "user_input": PROMPT,
        "plan": {},
        "architecture": {},
        "evaluation": {},
        "loop_count": 0,
        "max_loops": 3,
        "human_approved": None,
        "arm_template": {},
        "current_stage": "planner",
        "errors": [],
    }

    print("=" * 70)
    print("  AZURE SOLUTION ARCHITECT AI — HEADLESS RUN")
    print("=" * 70)
    print(f"\nThread ID: {thread_id}\n")
    print("INPUT PROMPT:")
    print(f"  {PROMPT}\n")
    print("=" * 70)

    arm_template = {}
    interrupted = False
    loop_count = 0

    # ── Phase 1: Run until interrupt ──────────────────────────────────────────
    async for event in pipeline.astream(initial_state, config, stream_mode="updates"):
        if "__interrupt__" in event:
            interrupted = True
            break

        for node_name, updates in event.items():
            if node_name.startswith("__"):
                continue

            print(f"\n{'─'*70}")
            print(f"  NODE: {node_name.upper()}")
            print(f"{'─'*70}")

            if node_name == "planner":
                print(_fmt_plan(updates.get("plan", {})))

            elif node_name == "architect":
                print(_fmt_arch(updates.get("architecture", {})))

            elif node_name == "evaluator":
                ev = updates.get("evaluation", {})
                print(_fmt_eval(ev))
                if not ev.get("passed", False):
                    loop_count_val = updates.get("loop_count", loop_count)
                    print(f"\n  >> Architecture did not pass WAF. Triggering redesign loop...")

            elif node_name == "redesigner":
                loop_count = updates.get("loop_count", loop_count + 1)
                print(f"  Redesign loop #{loop_count}")
                arch = updates.get("architecture", {})
                print(_fmt_arch(arch))
                notes = arch.get("redesign_notes", [])
                if notes:
                    print("  Changes Made:")
                    for note in notes[:5]:
                        print(f"    * {note}")

            elif node_name == "arm_generator":
                arm_template = updates.get("arm_template", {})
                rc = len(arm_template.get("resources", []))
                print(f"  ARM template generated with {rc} resource definitions.")

            errors = updates.get("errors", [])
            if errors:
                print(f"  WARNINGS: {errors[-1]}")

    # ── Phase 2: Auto-approve and resume ─────────────────────────────────────
    if interrupted:
        graph_state = pipeline.get_state(config)
        arch = graph_state.values.get("architecture", {})
        ev = graph_state.values.get("evaluation", {})

        print(f"\n{'='*70}")
        print("  HUMAN APPROVAL STEP (auto-approving)")
        print(f"{'='*70}")
        print(f"  Architecture : {arch.get('architecture_name', 'N/A')}")
        print(f"  WAF Score    : {ev.get('overall_score', 0)}/100")
        print(f"  Decision     : AUTO-APPROVED ✅")

        async for event in pipeline.astream(Command(resume=True), config, stream_mode="updates"):
            if "__interrupt__" in event:
                break

            for node_name, updates in event.items():
                if node_name.startswith("__"):
                    continue

                print(f"\n{'─'*70}")
                print(f"  NODE: {node_name.upper()}")
                print(f"{'─'*70}")

                if node_name == "arm_generator":
                    arm_template = updates.get("arm_template", {})
                    rc = len(arm_template.get("resources", []))
                    print(f"  ARM template generated with {rc} resource definitions.")

                errors = updates.get("errors", [])
                if errors:
                    print(f"  WARNINGS: {errors[-1]}")

    # ── Phase 3: Print ARM template ───────────────────────────────────────────
    if arm_template:
        print(f"\n{'='*70}")
        print("  DEPLOYABLE ARM TEMPLATE")
        print(f"{'='*70}")
        print(json.dumps(arm_template, indent=2))

        rc = len(arm_template.get("resources", []))
        pc = len(arm_template.get("parameters", {}))
        oc = len(arm_template.get("outputs", {}))
        print(f"\n{'='*70}")
        print("  PIPELINE COMPLETE")
        print(f"{'='*70}")
        print(f"  Resources  : {rc}")
        print(f"  Parameters : {pc}")
        print(f"  Outputs    : {oc}")
        print("\n  Deploy with Azure CLI:")
        print("    az deployment group create \\")
        print("      --resource-group <your-rg> \\")
        print("      --template-file template.json \\")
        print("      --parameters environment=prod namingPrefix=myapp")
    else:
        print(f"\n{'='*70}")
        print("  PIPELINE COMPLETE (no ARM template generated)")
        print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
