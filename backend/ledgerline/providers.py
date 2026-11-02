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
        effort = self.cfg.effort_override or effort
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


def schema_instructions(schema: dict) -> str:
    return ("\n\nRespond with ONLY one JSON object (no prose, no code fences) that matches this JSON Schema; every "
            "property is required:\n" + json.dumps(strictify(schema), ensure_ascii=False))


def structured_request(provider: Provider, name: str, schema: dict) -> dict:
    """kwargs that make a chat call return `schema`-shaped JSON on this provider ("prompt" mode: none, the schema
    goes into the instructions instead, see schema_instructions)."""
    if provider.cfg.structured == "prompt":
        return {}
    if provider.cfg.structured == "json_schema":
        return {"response_format": {"type": "json_schema", "json_schema": {"name": name, "schema": schema}}}
    tool = {"type": "function", "function": {"name": name, "description": "Return the result.", "parameters": schema}}
    return {"tools": [tool], "tool_choice": {"type": "function", "function": {"name": name}}}


def structured_result(res: LLMResult, name: str) -> Any:
    for tc in res.tool_calls:
        if tc.function.name == name:
            return json.loads(tc.function.arguments or "{}")
    return parse_json_loose(res.text)


# ---------------------------------------------------------------- media models on Meta Model API
BOX = re.compile(r"<\|box;x1=(\d+);y1=(\d+);x2=(\d+);y2=(\d+);w=(\d+);h=(\d+)\|>")


@dataclass
class MediaResult:
    data: dict
    latency_ms: int
    cost_usd: float
    model: str


class MetaMedia:
    """Muse Voice Transcribe (speech to text) and SAM 3.1 (segmentation) on Meta Model API."""

    def __init__(self, base_url: str, api_key: str, asr_model: str, sam_model: str, prices: dict):
        self.base_url, self.api_key = base_url.rstrip("/"), api_key
        self.asr_model, self.sam_model, self.prices = asr_model, sam_model, prices

    async def transcribe(self, wav: bytes, *, languages: list[str], keywords: list[str]) -> MediaResult:
        import httpx

        req = {"model": self.asr_model, "audioEncoding": "WAV", "mode": "ENDPOINTING",
               "languageBias": languages, "keywords": keywords[:50]}
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=180) as c:
            r = await c.post(f"{self.base_url}/asr/transcribe",
                             headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
                             files={"request": (None, json.dumps(req), "application/json"),
                                    "audio": ("memo.wav", wav, "audio/wav")})
        if r.status_code != 200:
            raise ProviderError(f"transcribe HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        cost = data.get("audioDurationMs", 0) / 3_600_000 * self.prices["asr_per_hour"]
        return MediaResult(data, int((time.perf_counter() - t0) * 1000), cost, self.asr_model)

    async def segment(self, jpeg: bytes, phrase: str) -> MediaResult:
        """Every instance of `phrase` in the image as a box normalized to the 0-1000 grid."""
        import base64

        import httpx

        body = {"model": self.sam_model, "stream": True, "input": [{"type": "message", "role": "user", "content": [
            {"type": "input_text", "text": phrase},
            {"type": "input_image", "image_url": "data:image/jpeg;base64," + base64.b64encode(jpeg).decode()}]}]}
        text = ""
        t0 = time.perf_counter()
        async with httpx.AsyncClient(timeout=180) as c:
            async with c.stream("POST", f"{self.base_url}/responses", json=body,
                                headers={"Authorization": f"Bearer {self.api_key}", "Accept": "text/event-stream"}) as r:
                if r.status_code != 200:
                    raise ProviderError(f"segment HTTP {r.status_code}: {(await r.aread())[:300]!r}")
                async for line in r.aiter_lines():
                    if not line.startswith("data: ") or line == "data: [DONE]":
                        continue
                    ev = json.loads(line[6:])
                    if ev.get("type") == "response.output_text.delta":
                        text += ev.get("delta", "")
                    elif ev.get("type") == "error":
                        raise ProviderError(f"segment error: {ev}")
        boxes = []
        for x1, y1, x2, y2, w, h in BOX.findall(text):
            x1, y1, x2, y2, w, h = map(int, (x1, y1, x2, y2, w, h))
            boxes.append([round(x1 * 1000 / w), round(y1 * 1000 / h), round(x2 * 1000 / w), round(y2 * 1000 / h)])
        return MediaResult({"phrase": phrase, "count": len(boxes), "boxes": boxes},
                           int((time.perf_counter() - t0) * 1000), self.prices["sam_per_image"], self.sam_model)
