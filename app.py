import os
import uuid
import json

from dotenv import load_dotenv

load_dotenv()

import chainlit as cl
from langgraph.types import Command

from graph import pipeline


# ─── Display helpers ─────────────────────────────────────────────────────────

NODE_DISPLAY = {
    "planner": "📋 Planner Agent",
    "architect": "🏗️ Architect Agent",
    "evaluator": "⚖️ Evaluator Agent",
    "redesigner": "🔄 Redesigner Agent",
    "arm_generator": "📄 ARM Generator",
    "human_approval": "👤 Human Approval",
}


def _format_plan(plan: dict) -> str:
    if not plan:
        return "_No plan data available._"
    lines = [
        f"**Workload:** {plan.get('workload_type', 'N/A')}",
        f"**Scale:** {plan.get('scale', 'N/A')}",
        f"**Regions:** {', '.join(plan.get('regions', ['N/A']))}",
        f"**Availability:** {plan.get('availability_requirement', 'N/A')}",
        f"**Key Services:** {', '.join(plan.get('key_services', []))}",
    ]
    constraints = plan.get("constraints", {})
    budget = constraints.get("budget_usd_monthly")
    if budget:
        lines.append(f"**Budget:** ${budget:,}/month")
    compliance = constraints.get("compliance", [])
    if compliance:
        lines.append(f"**Compliance:** {', '.join(compliance)}")
    nf = plan.get("non_functional", {})
    if nf.get("security"):
        lines.append(f"**Security Notes:** {nf['security']}")
    return "\n".join(lines)


def _render_components(components: list, show_why: bool = True) -> list:
    """Render a components list into markdown lines."""
    lines = [
        f"### 📦 Components ({len(components)} resources)",
        "",
        "| # | Resource Name | Azure Service | SKU / Size | Tier | Redundancy | Region |",
        "|---|--------------|--------------|------------|------|-----------|--------|",
    ]
    for i, comp in enumerate(components, 1):
        lines.append(
            f"| {i} | **{comp.get('name','—')}** "
            f"| {comp.get('azure_service','—')} "
            f"| `{comp.get('sku','N/A')}` "
            f"| {comp.get('tier','—')} "
            f"| {comp.get('redundancy','None')} "
            f"| {comp.get('region','—')} |"
        )
    if show_why:
        lines += ["", "**Design Decisions (WHY + Trade-offs):**", ""]
        for comp in components:
            why      = comp.get("why", "")
            tradeoff = comp.get("tradeoffs", "")
            purpose  = comp.get("purpose", "")
            if why or tradeoff:
                lines.append(f"**{comp.get('name','—')}** — {purpose}")
                if why:
                    lines.append(f"- 🎯 **Why:** {why}")
                if tradeoff:
                    lines.append(f"- ⚠️ **Trade-off:** {tradeoff}")
                lines.append("")
    return lines


def _render_networking(networking: dict) -> list:
    if not networking:
        return []
    lines = [
        "### 🌐 Networking",
        "",
        f"- **VNet CIDR:** `{networking.get('vnet_cidr','N/A')}`",
        f"- **DNS:** {networking.get('dns','N/A')}",
    ]
    private_eps = networking.get("private_endpoints", [])
    if private_eps:
        lines.append(f"- **Private Endpoints:** {', '.join(f'`{e}`' for e in private_eps)}")
    subnets = networking.get("subnets", [])
    if subnets:
        lines += [
            "",
            "| Subnet | CIDR | Purpose |",
            "|--------|------|---------|",
        ]
        for sn in subnets:
            lines.append(f"| {sn.get('name','—')} | `{sn.get('cidr','—')}` | {sn.get('purpose','—')} |")
    return lines


def _render_security(security: dict) -> list:
    if not security:
        return []
    lines = [
        "### 🔐 Security",
        "",
        f"- **Identity:** {security.get('identity','N/A')}",
        f"- **Key Vault:** {security.get('key_vault','N/A')}",
        f"- **Defender for Cloud:** {'✅ Enabled' if security.get('defender_for_cloud') else '❌ Disabled'}",
        f"- **DDoS Protection:** {'✅ Enabled' if security.get('ddos_protection') else '❌ Disabled'}",
    ]
    for role in security.get("rbac", []):
        lines.append(f"  - {role}")
    return lines


def _render_dr(dr: dict) -> list:
    if not dr:
        return []
    primary   = dr.get("primary_region", "—")
    secondary = dr.get("secondary_region", "—")
    return [
        "### 🔄 Disaster Recovery",
        "",
        "| Strategy | Primary Region | Secondary Region | RTO | RPO |",
        "|----------|---------------|-----------------|-----|-----|",
        f"| **{dr.get('strategy','N/A')}** | {primary} | {secondary} "
        f"| {dr.get('rto_minutes','—')} min | {dr.get('rpo_minutes','—')} min |",
        "",
        f"- **Failover Mechanism:** {dr.get('failover_mechanism','N/A')}",
    ]


def _render_monitoring(monitoring: dict) -> list:
    if not monitoring:
        return []
    lines = [
        "### 📊 Monitoring & Alerting",
        "",
        f"- **Tools:** {', '.join(monitoring.get('tools', []))}",
        f"- **Dashboards:** {', '.join(monitoring.get('dashboards', []))}",
    ]
    alerts = monitoring.get("alerts", [])
    if alerts:
        lines += [
            "",
            "**Configured Alerts:**",
            "",
            "| Alert | Metric | Threshold | Severity | Action |",
            "|-------|--------|-----------|----------|--------|",
        ]
        for a in alerts:
            lines.append(
                f"| {a.get('name','—')} "
                f"| `{a.get('metric','—')}` "
                f"| {a.get('threshold','—')} "
                f"| **{a.get('severity','—')}** "
                f"| {a.get('action','—')} |"
            )
    return lines


def _render_cost_breakdown(cost_breakdown: list, total: int) -> list:
    if not cost_breakdown:
        return [f"### 💰 Estimated Cost", "", f"**${total:,} / month**"]
    lines = [
        "### 💰 Cost Breakdown",
        "",
        "| Service | SKU | Monthly (USD) | Notes |",
        "|---------|-----|--------------|-------|",
    ]
    for item in cost_breakdown:
        usd = item.get("monthly_usd", 0)
        lines.append(
            f"| {item.get('service','—')} "
            f"| `{item.get('sku','—')}` "
            f"| **${usd:,}** "
            f"| {item.get('notes','—')} |"
        )
    lines += ["", f"**Total: ${total:,} / month**"]
    return lines


def _render_alternative(alt: dict) -> list:
    if not alt:
        return []
    alt_cost = alt.get("estimated_monthly_cost_usd", 0)
    lines = [
        "### 🔀 Alternative Variant — " + alt.get("variant_label", "Cost-Optimized"),
        "",
        f"> {alt.get('description', '')}",
        "",
        f"**Best for:** {alt.get('best_for', 'N/A')}",
        f"**Estimated Cost:** ${alt_cost:,} / month",
        "",
        "**Key Differences from Primary:**",
    ]
    for diff in alt.get("key_differences", []):
        lines.append(f"- {diff}")
    return lines


def _render_comparison(comparison: dict) -> list:
    if not comparison:
        return []
    lines = [
        "### ⚖️ Variant Comparison",
        "",
        "| Performance-Optimized ✅ | Cost-Optimized 💸 |",
        "|--------------------------|------------------|",
    ]
    primary_adv = comparison.get("primary_advantages", [])
    alt_adv     = comparison.get("alternative_advantages", [])
    max_rows = max(len(primary_adv), len(alt_adv))
    for i in range(max_rows):
        p = primary_adv[i] if i < len(primary_adv) else ""
        a = alt_adv[i]     if i < len(alt_adv)     else ""
        lines.append(f"| {p} | {a} |")
    lines += ["", f"**Recommendation:** {comparison.get('recommendation', '')}"]
    return lines


def _format_architecture(arch: dict) -> str:
    if not arch:
        return "_No architecture data available._"

    components     = arch.get("components", [])
    networking     = arch.get("networking", {})
    security       = arch.get("security", {})
    dr             = arch.get("disaster_recovery", {})
    monitoring     = arch.get("monitoring", {})
    cost_breakdown = arch.get("cost_breakdown", [])
    total_cost     = arch.get("estimated_monthly_cost_usd", 0)
    alt            = arch.get("alternative_variant", {})
    comparison     = arch.get("comparison", {})
    confidence     = arch.get("confidence_score")
    conf_reason    = arch.get("confidence_reasoning", "")
    variant_label  = arch.get("variant_label", "Performance-Optimized")

    lines = [
        f"## 🏗️ {arch.get('architecture_name', 'Azure Solution')}",
        f"**Variant:** {variant_label}",
        "",
        f"> {arch.get('description', '')}",
        "",
    ]

    # Confidence score
    if confidence is not None:
        bar = "█" * (confidence // 10) + "░" * (10 - confidence // 10)
        lines += [
            f"**🎯 Confidence Score: {confidence}/100** `{bar}`",
            f"_{conf_reason}_",
            "",
        ]

    lines += _render_components(components, show_why=True) + [""]
    lines += _render_networking(networking)   + [""]
    lines += _render_security(security)       + [""]
    lines += _render_dr(dr)                   + [""]
    lines += _render_monitoring(monitoring)   + [""]
    lines += _render_cost_breakdown(cost_breakdown, total_cost) + [""]

    if alt:
        lines += ["---", ""] + _render_alternative(alt) + [""]
    if comparison:
        lines += _render_comparison(comparison) + [""]

    return "\n".join(lines)


def _format_evaluation(eval_data: dict) -> str:
    if not eval_data:
        return "_No evaluation data available._"
    scores  = eval_data.get("scores", {})
    passed  = eval_data.get("passed", False)
    status  = "✅ PASSED" if passed else "❌ FAILED"
    overall = eval_data.get("overall_score", 0)
    conf    = eval_data.get("confidence_score")

    lines = [
        f"**Status:** {status} | **Overall Score:** {overall}/100",
        "",
        "| WAF Pillar | Score | Bar |",
        "|---|---|---|",
    ]
    pillar_data = [
        ("Reliability",            scores.get("reliability", 0)),
        ("Security",               scores.get("security", 0)),
        ("Cost Optimization",      scores.get("cost_optimization", 0)),
        ("Operational Excellence", scores.get("operational_excellence", 0)),
        ("Performance Efficiency", scores.get("performance_efficiency", 0)),
    ]
    for pillar, score in pillar_data:
        bar = "█" * (score // 10) + "░" * (10 - score // 10)
        lines.append(f"| {pillar} | **{score}/100** | `{bar}` |")

    if conf is not None:
        lines += [
            "",
            f"**🎯 Confidence Score: {conf}/100** — _{eval_data.get('confidence_reasoning','')}_",
        ]

    lines += ["", f"**Summary:** {eval_data.get('summary', '')}"]

    issues = eval_data.get("critical_issues", [])
    if issues:
        lines += ["", "**❌ Critical Issues:**"]
        for issue in issues:
            lines.append(f"- {issue}")

    strengths = eval_data.get("strengths", [])
    if strengths:
        lines += ["", "**✅ Strengths:**"]
        for s in strengths[:4]:
            lines.append(f"- {s}")

    improvements = eval_data.get("improvements", [])
    if improvements and not passed:
        lines += ["", "**💡 Improvements:**"]
        for imp in improvements[:4]:
            lines.append(f"- {imp}")

    return "\n".join(lines)


def _format_approval_summary(arch: dict, eval_data: dict) -> str:
    """Full structured architecture + WAF scores for the human approval card."""
    scores         = eval_data.get("scores", {})
    components     = arch.get("components", [])
    networking     = arch.get("networking", {})
    security       = arch.get("security", {})
    dr             = arch.get("disaster_recovery", {})
    monitoring     = arch.get("monitoring", {})
    cost_breakdown = arch.get("cost_breakdown", [])
    total_cost     = arch.get("estimated_monthly_cost_usd", 0)
    alt            = arch.get("alternative_variant", {})
    comparison     = arch.get("comparison", {})
    confidence     = arch.get("confidence_score")
    variant_label  = arch.get("variant_label", "Performance-Optimized")
    name           = arch.get("architecture_name", "Azure Solution")

    lines = [
        f"## 🏗️ {name}  ·  {variant_label}",
        "",
        f"> {arch.get('description', '')}",
        "",
    ]

    if confidence is not None:
        bar = "█" * (confidence // 10) + "░" * (10 - confidence // 10)
        lines += [
            f"**🎯 Confidence: {confidence}/100** `{bar}`  ·  "
            f"_{arch.get('confidence_reasoning','')}_",
            "",
        ]

    lines += ["---", ""]
    lines += _render_components(components, show_why=True) + [""]
    lines += _render_networking(networking)   + [""]
    lines += _render_security(security)       + [""]
    lines += _render_dr(dr)                   + [""]
    lines += _render_monitoring(monitoring)   + [""]
    lines += _render_cost_breakdown(cost_breakdown, total_cost) + [""]

    if alt:
        lines += ["---", ""] + _render_alternative(alt) + [""]
    if comparison:
        lines += _render_comparison(comparison) + [""]

    # WAF summary
    overall = eval_data.get("overall_score", 0)
    conf_eval = eval_data.get("confidence_score")
    lines += [
        "---",
        "",
        "### ⚖️ Well-Architected Framework Review",
        "",
        "| Pillar | Score |",
        "|--------|-------|",
        f"| Reliability | **{scores.get('reliability', 0)}/100** |",
        f"| Security | **{scores.get('security', 0)}/100** |",
        f"| Cost Optimization | **{scores.get('cost_optimization', 0)}/100** |",
        f"| Operational Excellence | **{scores.get('operational_excellence', 0)}/100** |",
        f"| Performance Efficiency | **{scores.get('performance_efficiency', 0)}/100** |",
        "",
        f"**Overall: {overall}/100**",
    ]
    if conf_eval is not None:
        lines.append(f"**Evaluator Confidence: {conf_eval}/100** — _{eval_data.get('confidence_reasoning','')}_")
    lines += ["", f"_{eval_data.get('summary', '')}_"]

    return "\n".join(lines)


# ─── Gap detection display helper ────────────────────────────────────────────

def _format_gaps(gaps: list[dict], completeness: int) -> str:
    if not gaps:
        return "✅ Requirements are complete — no gaps detected."

    impact_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}
    bar = "█" * (completeness // 10) + "░" * (10 - completeness // 10)

    lines = [
        "## ⚠️ Requirements Gap Analysis",
        "",
        f"**Completeness Score: {completeness}/100** `{bar}`",
        "",
        "The following information was not provided. The architect will use the stated assumptions — "
        "you can proceed or clarify before design begins.",
        "",
        "| Impact | Category | What's Missing | Assumption Being Made |",
        "|--------|----------|---------------|----------------------|",
    ]
    for g in sorted(gaps, key=lambda x: {"HIGH": 0, "MEDIUM": 1, "LOW": 2}.get(x.get("impact", "LOW"), 3)):
        icon    = impact_icon.get(g.get("impact", "LOW"), "🟢")
        cat     = g.get("category", "—")
        gap_txt = g.get("gap", "—")
        assume  = g.get("assumption", "—")
        reason  = g.get("impact_reason", "")
        lines.append(f"| {icon} **{g.get('impact','LOW')}** | {cat} | {gap_txt} | _{assume}_ |")
        if reason and g.get("impact") == "HIGH":
            lines.append(f"| | | ⚠️ _Risk: {reason}_ | |")

    high_count   = sum(1 for g in gaps if g.get("impact") == "HIGH")
    medium_count = sum(1 for g in gaps if g.get("impact") == "MEDIUM")
    low_count    = sum(1 for g in gaps if g.get("impact") == "LOW")

    lines += [
        "",
        f"**{len(gaps)} gaps detected:** {high_count} 🔴 High  ·  {medium_count} 🟡 Medium  ·  {low_count} 🟢 Low",
        "",
        "_High-impact gaps may significantly change the architecture if clarified._",
    ]
    return "\n".join(lines)


# ─── Chainlit event handlers ─────────────────────────────────────────────────

@cl.on_chat_start
async def on_chat_start():
    await cl.Message(
        content="""# 🏗️ Azure Solution Architect AI

Welcome! I'm your AI-powered Azure Solution Architect — a **multi-agent pipeline** that designs, evaluates, and generates production-ready Azure architectures.

---

**Pipeline Stages:**

| Stage | Agent | What it does |
|-------|-------|-------------|
| 1 | 📋 Planner | Extracts requirements + detects gaps |
| 1b | 👤 You | Review gaps & confirm or clarify |
| 2 | 🏗️ Architect | Designs complete Azure topology (2 variants) |
| 3 | ⚖️ Evaluator | WAF review + confidence scoring |
| 4 | 🔄 Redesigner | Auto-fixes issues (up to 3 loops) |
| 5 | 👤 You | Review & approve final design |
| 6 | 📄 ARM Generator | Produces a deployable ARM template |

---

**Please describe your Azure workload.** Even a rough description works — the Planner will detect what's missing and ask you to clarify before designing.

_Example: "E-commerce site, 50K daily users, payment processing, HIPAA, East US, $10K/month budget"_"""
    ).send()


@cl.on_message
async def on_message(message: cl.Message):
    thread_id = str(uuid.uuid4())
    config    = {"configurable": {"thread_id": thread_id}}

    initial_state = {
        "user_input":         message.content,
        "plan":               {},
        "requirements_gaps":  [],
        "gap_confirmed":      None,
        "architecture":       {},
        "evaluation":         {},
        "loop_count":         0,
        "max_loops":          3,
        "human_approved":     None,
        "arm_template":       {},
        "current_stage":      "planner",
        "errors":             [],
    }

    await cl.Message(
        content=f"🚀 **Launching Azure Architecture Pipeline...**\n\n_Thread: `{thread_id}`_"
    ).send()

    arm_template  = {}
    approved      = False
    current_loop  = 0
    stream_input  = initial_state   # first call uses state dict; resumes use Command

    try:
        # ── Main streaming loop — handles multiple interrupt types ─────────
        while True:
            interrupted      = False
            interrupt_type   = None
            interrupt_payload = {}

            async for event in pipeline.astream(stream_input, config, stream_mode="updates"):
                if "__interrupt__" in event:
                    interrupted      = True
                    raw_interrupts   = event["__interrupt__"]
                    if raw_interrupts:
                        interrupt_payload = raw_interrupts[0].value if hasattr(raw_interrupts[0], "value") else {}
                        interrupt_type    = interrupt_payload.get("type", "human_approval")
                    break

                for node_name, updates in event.items():
                    if node_name.startswith("__"):
                        continue

                    display_name = NODE_DISPLAY.get(node_name, node_name.title())
                    errors       = updates.get("errors", [])

                    # ── Planner ──────────────────────────────────────────
                    if node_name == "planner":
                        async with cl.Step(name=display_name, type="tool") as step:
                            step.output = _format_plan(updates.get("plan", {}))

                    # ── Architect ────────────────────────────────────────
                    elif node_name == "architect":
                        async with cl.Step(name=display_name, type="tool") as step:
                            step.output = _format_architecture(updates.get("architecture", {}))

                    # ── Evaluator ────────────────────────────────────────
                    elif node_name == "evaluator":
                        eval_data = updates.get("evaluation", {})
                        async with cl.Step(name=display_name, type="tool") as step:
                            step.output = _format_evaluation(eval_data)
                        if not eval_data.get("passed", False):
                            issues = eval_data.get("critical_issues", [])
                            if current_loop < initial_state["max_loops"]:
                                await cl.Message(
                                    content=(
                                        f"🔁 **Redesign Loop {current_loop + 1}/{initial_state['max_loops']}**"
                                        f" — fixing {len(issues)} critical issue(s)"
                                    )
                                ).send()

                    # ── Redesigner ───────────────────────────────────────
                    elif node_name == "redesigner":
                        current_loop = updates.get("loop_count", current_loop + 1)
                        arch = updates.get("architecture", {})
                        async with cl.Step(name=display_name, type="tool") as step:
                            lines = [_format_architecture(arch)]
                            notes = arch.get("redesign_notes", [])
                            if notes:
                                lines += ["\n**Changes Made:**"] + [f"- {n}" for n in notes[:5]]
                            step.output = "\n".join(lines)

                    # ── ARM Generator ────────────────────────────────────
                    elif node_name == "arm_generator":
                        arm_template = updates.get("arm_template", {})
                        async with cl.Step(name=display_name, type="tool") as step:
                            step.output = (
                                f"ARM template generated with "
                                f"**{len(arm_template.get('resources', []))}** resource definitions."
                            )

                    if errors:
                        await cl.Message(content=f"⚠️ _{errors[-1]}_").send()

            # ── No interrupt — pipeline finished ─────────────────────────
            if not interrupted:
                break

            # ── Handle: Gap Review interrupt ──────────────────────────────
            if interrupt_type == "gap_review":
                graph_state   = pipeline.get_state(config)
                gaps          = graph_state.values.get("requirements_gaps", [])
                completeness  = graph_state.values.get("plan", {}).get("completeness_score", 100)

                gaps_content = _format_gaps(gaps, completeness)

                res = await cl.AskActionMessage(
                    content=gaps_content + "\n\n---\n_How would you like to proceed?_",
                    actions=[
                        cl.Action(
                            name="proceed",
                            label="✅ Proceed with These Assumptions",
                            payload={"action": "proceed"},
                        ),
                        cl.Action(
                            name="clarify",
                            label="📝 Let Me Clarify First",
                            payload={"action": "clarify"},
                        ),
                    ],
                ).send()

                action = "proceed"
                if res:
                    action = res.get("name") or res.get("payload", {}).get("action", "proceed")

                if action == "clarify":
                    clarification_msg = await cl.AskUserMessage(
                        content=(
                            "Please provide the missing details. You can address any or all gaps above.\n\n"
                            "_Examples: 'Budget is $8K/month, PCI-DSS required, peak traffic is 5K concurrent users'_"
                        ),
                        timeout=600,
                    ).send()
                    clarification_text = clarification_msg.get("output", "").strip() if clarification_msg else ""

                    if clarification_text:
                        await cl.Message(
                            content=f"📝 **Clarification received.** Re-analyzing requirements..."
                        ).send()
                        stream_input = Command(resume=clarification_text)
                    else:
                        await cl.Message(content="No clarification provided — proceeding with assumptions.").send()
                        stream_input = Command(resume=True)
                else:
                    await cl.Message(content="✅ **Proceeding with stated assumptions.** Designing architecture...").send()
                    stream_input = Command(resume=True)

            # ── Handle: Human Approval interrupt ──────────────────────────
            elif interrupt_type == "human_approval":
                graph_state = pipeline.get_state(config)
                arch        = graph_state.values.get("architecture", {})
                eval_data   = graph_state.values.get("evaluation", {})
                summary     = _format_approval_summary(arch, eval_data)

                res = await cl.AskActionMessage(
                    content=(
                        "## 👤 Architecture Review Required\n\n"
                        f"{summary}\n\n---\n"
                        "_Approve to generate a deployable ARM template, or reject to end._"
                    ),
                    actions=[
                        cl.Action(
                            name="approve",
                            label="✅ Approve → Generate ARM Template",
                            payload={"value": "approve"},
                        ),
                        cl.Action(
                            name="reject",
                            label="❌ Reject Pipeline",
                            payload={"value": "reject"},
                        ),
                    ],
                ).send()

                if res:
                    approved = (
                        res.get("name") == "approve"
                        or res.get("payload", {}).get("value") == "approve"
                    )
                else:
                    approved = False

                if approved:
                    await cl.Message(content="✅ **Approved!** Generating deployable ARM template...").send()
                else:
                    await cl.Message(content="❌ **Pipeline rejected** by user.").send()

                stream_input = Command(resume=approved)

                if not approved:
                    break   # no need to continue streaming after rejection

            else:
                # Unknown interrupt type — resume and continue
                stream_input = Command(resume=True)

        # ── Display ARM template ──────────────────────────────────────────
        if arm_template and approved:
            arm_json = json.dumps(arm_template, indent=2)
            await cl.Message(
                content=(
                    "## 📄 Deployable ARM Template\n\n"
                    f"```json\n{arm_json}\n```"
                )
            ).send()

            await cl.Message(
                content=(
                    "## ✅ Pipeline Complete!\n\n"
                    f"**ARM Template:** {len(arm_template.get('resources', []))} resources  ·  "
                    f"{len(arm_template.get('parameters', {}))} parameters  ·  "
                    f"{len(arm_template.get('outputs', {}))} outputs\n\n"
                    "**Deploy with Azure CLI:**\n"
                    "```bash\n"
                    "az deployment group create \\\n"
                    "  --resource-group <your-rg> \\\n"
                    "  --template-file template.json \\\n"
                    "  --parameters environment=prod namingPrefix=myapp\n"
                    "```"
                )
            ).send()

    except Exception as exc:
        msg = str(exc)
        if any(k in msg for k in ("quota", "billing", "insufficient", "rate limit")):
            await cl.Message(
                content=(
                    "## ❌ Azure OpenAI — Quota / Rate Limit\n\n"
                    "**Fix:** portal.azure.com → Azure OpenAI → Deployments → increase TPM limit."
                )
            ).send()
        else:
            await cl.Message(
                content=f"❌ **Pipeline Error**\n\n```\n{type(exc).__name__}: {exc}\n```"
            ).send()
        raise
