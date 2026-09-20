"""Per-call usage logging and cost estimation.

PRICING is the single place where per-token prices live. Rates are USD per
1M tokens. Verify against https://www.anthropic.com/pricing before quoting
numbers in DELIVERY_NOTES.md - the values below are a snapshot.
"""
from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field, asdict

log = logging.getLogger("pipeline.cost")

# USD per 1,000,000 tokens. Snapshot date: 2026-09-20.
PRICING: dict[str, dict[str, float]] = {
    "claude-sonnet-5": {
        "input": 2.00,
        "output": 10.00,
        "cache_write": 2.50,   # 1.25x input
        "cache_read": 0.20,    # 0.1x input
    },
    "claude-haiku-4-5-20251001": {
        "input": 1.00,
        "output": 5.00,
        "cache_write": 1.25,
        "cache_read": 0.10,
    },
}


def price_for(model: str) -> dict[str, float]:
    if model in PRICING:
        return PRICING[model]
    # Allow dated aliases like "claude-sonnet-5-2026xxxx" to fall back to the base id.
    for key, rates in PRICING.items():
        if model.startswith(key):
            return rates
    log.warning("No pricing entry for model %s - cost will be reported as 0", model)
    return {"input": 0.0, "output": 0.0, "cache_write": 0.0, "cache_read": 0.0}


@dataclass
class CallRecord:
    purpose: str            # e.g. "parse_packing_list", "vision:photo1", "identity_judgment"
    model: str
    input_tokens: int
    output_tokens: int
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    seconds: float = 0.0
    cost_usd: float = 0.0
    stop_reason: str | None = None


@dataclass
class CostTracker:
    """Collects one CallRecord per API call. Thread-safe (vision calls run in parallel)."""
    calls: list[CallRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    started_at: float = field(default_factory=time.perf_counter)

    def record(self, purpose: str, model: str, usage, seconds: float, stop_reason: str | None = None) -> CallRecord:
        rates = price_for(model)
        inp = int(getattr(usage, "input_tokens", 0) or 0)
        out = int(getattr(usage, "output_tokens", 0) or 0)
        cr = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cw = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        cost = (
            inp * rates["input"]
            + out * rates["output"]
            + cr * rates["cache_read"]
            + cw * rates["cache_write"]
        ) / 1_000_000
        rec = CallRecord(purpose, model, inp, out, cr, cw, round(seconds, 3), round(cost, 6), stop_reason)
        with self._lock:
            self.calls.append(rec)
        log.info(
            "api_call purpose=%s model=%s input_tokens=%d output_tokens=%d cache_read=%d cache_write=%d "
            "seconds=%.2f cost_usd=%.6f stop_reason=%s",
            purpose, model, inp, out, cr, cw, seconds, cost, stop_reason,
        )
        return rec

    def summary(self) -> dict:
        with self._lock:
            calls = list(self.calls)
        return {
            "total_seconds": round(time.perf_counter() - self.started_at, 3),
            "total_cost_usd": round(sum(c.cost_usd for c in calls), 6),
            "total_input_tokens": sum(c.input_tokens for c in calls),
            "total_output_tokens": sum(c.output_tokens for c in calls),
            "pricing_usd_per_mtok": PRICING,
            "calls": [asdict(c) for c in calls],
        }
