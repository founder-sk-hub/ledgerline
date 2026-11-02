"""Model providers. Both are Meta models behind OpenAI-compatible endpoints:

* meta    -> Muse Spark 1.3 on Meta Model API (api.meta.ai/v1)
* private -> Muse Spark Open (open weights) on Baseten, or any self-hosted OpenAI-compatible server
"""

from __future__ import annotations

import asyncio
import json
import random
import re
import time
from dataclasses import dataclass, field
from typing import Any

import openai
from openai import AsyncOpenAI

from .config import DEFAULT_PRICE, PRICES, ProviderConfig


@dataclass
class LLMResult:
    message: Any  # openai ChatCompletionMessage
    usage: dict
    latency_ms: int
    cost_usd: float
    response_id: str = ""
    extra: dict = field(default_factory=dict)

    @property
    def text(self) -> str:
        return self.message.content or ""

    @property
    def tool_calls(self) -> list:
        return list(self.message.tool_calls or [])


class ProviderError(RuntimeError):
    pass


def _usage(u: Any) -> dict:
    if u is None:
        return {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "reasoning_tokens": 0}
    ptd = getattr(u, "prompt_tokens_details", None)
    ctd = getattr(u, "completion_tokens_details", None)
    return {
        "input_tokens": int(getattr(u, "prompt_tokens", 0) or 0),
        "output_tokens": int(getattr(u, "completion_tokens", 0) or 0),
        "cached_tokens": int(getattr(ptd, "cached_tokens", 0) or 0) if ptd else 0,
        "reasoning_tokens": int(getattr(ctd, "reasoning_tokens", 0) or 0) if ctd else 0,
    }


def cost_of(model: str, usage: dict) -> float:
    p = PRICES.get(model, DEFAULT_PRICE)
    fresh = max(usage["input_tokens"] - usage["cached_tokens"], 0)
    return (fresh * p["input"] + usage["cached_tokens"] * p["cached"] + usage["output_tokens"] * p["output"]) / 1e6


class Provider:
    def __init__(self, cfg: ProviderConfig, concurrency: int = 6):
        self.cfg = cfg
        self.client = AsyncOpenAI(base_url=cfg.base_url, api_key=cfg.api_key or "missing", timeout=180, max_retries=0)
        self.sem = asyncio.Semaphore(concurrency)

    def instructions(self, text: str) -> dict:
        return {"role": self.cfg.developer_role, "content": text}

    async def chat(self, messages: list[dict], *, tools: list[dict] | None = None, tool_choice: Any = None,
                   response_format: dict | None = None, effort: str | None = None,
                   max_tokens: int = 4096) -> LLMResult:
        kwargs: dict[str, Any] = {"model": self.cfg.model, "messages": messages, "max_completion_tokens": max_tokens}
        if tools:
            kwargs["tools"] = strict_tools(tools)
            if tool_choice is not None:
                kwargs["tool_choice"] = tool_choice
        if response_format:
            if response_format.get("type") == "json_schema":
                js = response_format["json_schema"]
                response_format = {**response_format, "json_schema": {**js, "schema": strictify(js["schema"])}}
            kwargs["response_format"] = response_format
        if effort and self.cfg.reasoning_effort:
            kwargs["reasoning_effort"] = effort

        delay = 1.0
        for attempt in range(5):
            t0 = time.perf_counter()
            try:
                async with self.sem:
                    resp = await self.client.chat.completions.create(**kwargs)
            except (openai.RateLimitError, openai.APITimeoutError, openai.APIConnectionError,
                    openai.InternalServerError) as e:
                if attempt == 4:
                    raise ProviderError(f"{type(e).__name__}: {e}") from e
                await asyncio.sleep(delay + random.random())
                delay *= 2
                continue
            except openai.BadRequestError as e:
                # Degrade gracefully on parameters a given server doesn't accept.
                msg = str(e).lower()
                if kwargs.get("tool_choice") not in (None, "auto") and "tool_choice" in msg:
                    kwargs["tool_choice"] = "auto"  # Meta Model API only accepts "auto"
                    continue
                if "reasoning_effort" in kwargs and "reasoning" in msg:
                    kwargs.pop("reasoning_effort")
                    continue
                if kwargs["messages"] and kwargs["messages"][0].get("role") == "developer" and "role" in msg:
                    kwargs["messages"] = [{**m, "role": "system"} if m.get("role") == "developer" else m
                                          for m in kwargs["messages"]]
                    continue
                raise ProviderError(f"BadRequest: {e}") from e
            except openai.APIStatusError as e:
                raise ProviderError(f"HTTP {e.status_code}: {e}") from e
            latency = int((time.perf_counter() - t0) * 1000)
            usage = _usage(resp.usage)
            if not resp.choices:
                raise ProviderError("empty response (no choices)")
            return LLMResult(resp.choices[0].message, usage, latency, cost_of(self.cfg.model, usage),
                             response_id=getattr(resp, "id", "") or "")
        raise ProviderError("unreachable")


def parse_json_loose(text: str) -> Any:
    """Parse JSON from a model reply that may wrap it in prose or code fences."""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    if m:
        text = m.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    for open_, close in (("{", "}"), ("[", "]")):
        i, j = text.find(open_), text.rfind(close)
        if i != -1 and j > i:
            try:
                return json.loads(text[i : j + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError("no JSON object found in model output")


def strictify(schema: Any) -> Any:
    """Every object closed and fully required. Muse Spark's constrained decoding can invent keys
    for optional properties, so absent values are expressed as "" / 0 / [] instead."""
    if isinstance(schema, dict):
        out = {k: strictify(v) for k, v in schema.items()}
        if out.get("type") == "object" and "properties" in out:
            out["additionalProperties"] = False
            out["required"] = list(out["properties"])
        return out
    if isinstance(schema, list):
        return [strictify(s) for s in schema]
    return schema


def strict_tools(tools: list[dict]) -> list[dict]:
    return [{**t, "function": {**t["function"], "parameters": strictify(t["function"]["parameters"])}} for t in tools]


def structured_request(provider: Provider, name: str, schema: dict) -> dict:
    """kwargs that make a chat call return `schema`-shaped JSON on this provider."""
    if provider.cfg.structured == "json_schema":
        return {"response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}}
    tool = {"type": "function", "function": {"name": name, "description": "Return the result.", "parameters": schema}}
    return {"tools": [tool], "tool_choice": {"type": "function", "function": {"name": name}}}


def structured_result(res: LLMResult, name: str) -> Any:
    for tc in res.tool_calls:
        if tc.function.name == name:
            return json.loads(tc.function.arguments or "{}")
    return parse_json_loose(res.text)
