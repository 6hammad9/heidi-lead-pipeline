"""The automatic quality gate: replaces a human reviewing the first batch. Pure."""

from pydantic import BaseModel

from pipeline import config
from pipeline.agent.schema import CLAIM_FIELDS, ResearchRecord
from pipeline.verify import VerificationStats

FAILURE_STOPS = {"error", "max_turns", "cost_cap", "invalid_submission", "refusal"}


class GateResult(BaseModel):
    passed: bool
    reasons: list[str]
    metrics: dict[str, float]


def evaluate(records: list[ResearchRecord], stats: VerificationStats) -> GateResult:
    ran = [r for r in records if r.stop != "no_pages"]  # the agent actually worked on these
    if not ran:
        return GateResult(passed=True, reasons=[], metrics={})
    submitted = [r.submission for r in ran if r.submission]
    claims = len(submitted) * len(CLAIM_FIELDS)
    unknown = sum(getattr(s, f).value is None for s in submitted for f in CLAIM_FIELDS)
    metrics = {
        "failure_rate": sum(r.stop in FAILURE_STOPS for r in ran) / len(ran),
        "verified_rate": stats.claims_verified / stats.claims_checked
        if stats.claims_checked
        else 1.0,
        "unknown_rate": unknown / claims if claims else 1.0,
        "avg_cost_usd": sum(r.cost_usd for r in ran) / len(ran),
    }
    limits = [
        ("failure_rate", metrics["failure_rate"] > config.GATE_MAX_FAILURE_RATE),
        ("verified_rate", metrics["verified_rate"] < config.GATE_MIN_VERIFIED_RATE),
        ("unknown_rate", metrics["unknown_rate"] > config.GATE_MAX_UNKNOWN_RATE),
        ("avg_cost_usd", metrics["avg_cost_usd"] > config.GATE_MAX_AVG_COST_USD),
    ]
    reasons = [f"{name} = {metrics[name]:.3f} is outside its limit" for name, bad in limits if bad]
    return GateResult(passed=not reasons, reasons=reasons, metrics=metrics)
