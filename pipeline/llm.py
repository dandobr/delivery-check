"""Thin wrapper around the Anthropic SDK that logs usage for every call.

All model calls in the pipeline go through `call_json`, so token logging and
cost accounting live in exactly one place.
"""
from __future__ import annotations

import json
import logging
import re
import time

import anthropic

from .cost import CostTracker

log = logging.getLogger("pipeline.llm")

VISION_MODEL = "claude-sonnet-5"             # vision pass + identity-mismatch judgment
PARSE_MODEL = "claude-haiku-4-5-20251001"    # packing-list PDF -> rows

_client: anthropic.Anthropic | None = None


def client() -> anthropic.Anthropic:
    """Lazily construct the SDK client so importing the pipeline never needs a key."""
    global _client
    if _client is None:
        _client = anthropic.Anthropic(max_retries=3)
    return _client


class LLMError(RuntimeError):
    pass


def _extract_json(text: str) -> dict:
    """Parse JSON from a text block, tolerating ``` fences."""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", t, re.S)
    if m:
        t = m.group(1).strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        start, end = t.find("{"), t.rfind("}")
        if start != -1 and end > start:
            return json.loads(t[start:end + 1])
        raise


def call_json(
    *,
    purpose: str,
    model: str,
    system: str,
    content: list | str,
    schema: dict,
    tracker: CostTracker,
    max_tokens: int = 8000,
    effort: str | None = None,
) -> dict:
    """Send one request and return the parsed JSON object.

    Uses structured outputs (output_config.format) so the reply is
    schema-valid JSON. Logs usage.input_tokens / usage.output_tokens.
    """
    kwargs: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": content}],
        "output_config": {"format": {"type": "json_schema", "schema": schema}},
    }
    if effort:
        kwargs["output_config"]["effort"] = effort

    t0 = time.perf_counter()
    try:
        response = client().messages.create(**kwargs)
    except anthropic.BadRequestError as e:
        # Only if the *structured-output / effort* parameters were rejected, retry as plain
        # JSON-in-text. Billing, auth and other 400s are re-raised untouched.
        msg = str(e).lower()
        if not any(k in msg for k in ("output_config", "output_format", "json_schema", "effort", "structured")):
            raise
        log.warning("%s: structured request rejected (%s); retrying as plain text", purpose, e)
        kwargs.pop("output_config")
        kwargs["system"] = system + "\n\nRespond with ONLY a JSON object matching this JSON schema, no prose:\n" + json.dumps(schema)
        response = client().messages.create(**kwargs)
    seconds = time.perf_counter() - t0

    tracker.record(purpose, model, response.usage, seconds, response.stop_reason)

    if response.stop_reason == "refusal":
        raise LLMError(f"{purpose}: model refused the request")
    if response.stop_reason == "max_tokens":
        raise LLMError(f"{purpose}: response truncated at max_tokens={max_tokens}")

    text = "".join(b.text for b in response.content if b.type == "text")
    try:
        return _extract_json(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"{purpose}: could not parse JSON from model output: {e}\n{text[:500]}") from e
