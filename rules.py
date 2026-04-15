"""
Deterministic rules engine — checks architecture dicts against hard rules
independently of the LLM evaluator. Results are injected into evaluation
so the LLM cannot silently ignore them.
"""

# ─── Rule definitions ─────────────────────────────────────────────────────────

RULES = [
    {
        "id": "R001",
        "name": "No Developer SKU in production",
        "check": lambda arch, dau=0: not any(
            "developer" in str(c.get("sku", "")).lower() or
            "developer" in str(c.get("tier", "")).lower()
            for c in arch.get("components", [])
        ),
        "severity": "critical",
        "message": "One or more components use a Developer SKU — not suitable for production.",
    },
    {
        "id": "R002",
        "name": "Cosmos DB provisioned throughput for high-DAU workloads",
        "check": lambda arch, dau=0: not (
            dau > 5000 and any(
                "cosmos" in c.get("azure_service", "").lower() and
                "serverless" in str(c.get("sku", "")).lower()
                for c in arch.get("components", [])
            )
        ),
        "severity": "critical",
        "message": "Cosmos DB Serverless chosen for >5,000 DAU workload — use Provisioned Throughput.",
    },
    {
        "id": "R003",
        "name": "Disaster Recovery has explicit primary and secondary regions",
        "check": lambda arch, dau=0: bool(
            arch.get("disaster_recovery", {}).get("primary_region") and
            arch.get("disaster_recovery", {}).get("secondary_region")
        ),
        "severity": "critical",
        "message": "Disaster Recovery is missing explicit primary_region or secondary_region.",
    },
    {
        "id": "R004",
        "name": "API Management not using Developer tier",
        "check": lambda arch, dau=0: not any(
            "api management" in c.get("azure_service", "").lower() and
            "developer" in str(c.get("sku", "")).lower()
            for c in arch.get("components", [])
        ),
        "severity": "critical",
        "message": "API Management is using Developer tier — use Standard or Premium for production.",
    },
    {
        "id": "R005",
        "name": "All components include WHY and trade-off reasoning",
        "check": lambda arch, dau=0: all(
            c.get("why") and c.get("tradeoffs")
            for c in arch.get("components", [])
        ),
        "severity": "warning",
        "message": "One or more components are missing 'why' or 'tradeoffs' reasoning fields.",
    },
    {
        "id": "R006",
        "name": "Per-service cost breakdown present",
        "check": lambda arch, dau=0: bool(arch.get("cost_breakdown")),
        "severity": "warning",
        "message": "Architecture is missing a per-service cost breakdown.",
    },
    {
        "id": "R007",
        "name": "Monitoring includes named alerts",
        "check": lambda arch, dau=0: bool(
            arch.get("monitoring", {}).get("alerts")
        ),
        "severity": "warning",
        "message": "Monitoring configuration has no named alerts defined.",
    },
    {
        "id": "R008",
        "name": "Architecture cost within budget cap",
        "check": lambda arch, dau=0, budget=float("inf"): (
            arch.get("estimated_monthly_cost_usd", 0) <= budget
        ),
        "severity": "warning",
        "message": "Architecture cost exceeds stated or assumed budget cap.",
    },
]


# ─── Runner ───────────────────────────────────────────────────────────────────

def run_rules_engine(
    variant: dict,
    dau: int = 0,
    budget: float = float("inf"),
) -> dict:
    """
    Run all RULES against a single architecture/variant dict.
    Returns a summary dict with violations[], warnings[], and passed bool.
    """
    violations: list[dict] = []
    warnings:   list[dict] = []

    for rule in RULES:
        try:
            if rule["id"] == "R002":
                passed = rule["check"](variant, dau)
            elif rule["id"] == "R008":
                passed = rule["check"](variant, dau=dau, budget=budget)
            else:
                passed = rule["check"](variant, dau)
        except Exception:
            passed = True   # never crash the pipeline on a rule error

        if not passed:
            finding = {
                "rule_id": rule["id"],
                "name":    rule["name"],
                "message": rule["message"],
            }
            if rule["severity"] == "critical":
                violations.append(finding)
            else:
                warnings.append(finding)

    return {
        "violations": violations,
        "warnings":   warnings,
        "passed":     len(violations) == 0,
    }
