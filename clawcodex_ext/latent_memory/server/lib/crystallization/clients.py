"""Embedding and LLM clients for semantic crystallization."""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.request
from typing import Any, Callable

from clawcodex_ext.latent_memory.server.token_usage import suppress_token_usage

logger = logging.getLogger("memory-server.crystallizer")


def embed_batch(texts: list[str], ollama_base_url: str, model: str) -> list[list[float]]:
    """Call Ollama /api/embed in batch to obtain embeddings."""
    if not texts:
        return []
    payload = json.dumps({"model": model, "input": texts}).encode("utf-8")
    url = f"{ollama_base_url.rstrip('/')}/api/embed"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["embeddings"]


def embed_batch_openai(
    texts: list[str], base_url: str, model: str, api_key: str = ""
) -> list[list[float]]:
    """Call the OpenAI-compatible embeddings interface."""
    if not texts:
        return []
    from openai import OpenAI

    client_kwargs: dict[str, Any] = {"api_key": api_key or "dummy", "timeout": 120.0}
    if base_url:
        client_kwargs["base_url"] = base_url
    client = OpenAI(**client_kwargs)
    response = client.embeddings.create(model=model, input=texts)
    return [item.embedding for item in response.data]


def build_embed_fn_from_config(config: dict[str, Any]) -> Callable[[list[str]], list[list[float]]]:
    """Build the crystallizer embedder from the main memory backend configuration."""
    embedder = config.get("embedder", {}) or {}
    provider = embedder.get("provider", "openai")
    embed_config = embedder.get("config", {}) or {}
    model = embed_config.get("model", "")
    if provider == "ollama":
        base_url = embed_config.get("ollama_base_url") or os.getenv(
            "OLLAMA_BASE_URL", "http://localhost:11434"
        )
        return lambda texts: embed_batch(texts, base_url, model)
    if provider == "openai":
        base_url = embed_config.get("openai_base_url") or os.getenv("OPENAI_BASE_URL", "")
        api_key = embed_config.get("api_key") or os.getenv("OPENAI_API_KEY", "")
        return lambda texts: embed_batch_openai(texts, base_url, model, api_key)
    raise ValueError(f"Unsupported crystallizer embedder provider: {provider}")


def _extract_json_object(raw: str) -> dict[str, Any]:
    import re

    json_str = raw.strip()
    code_block_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", json_str)
    if code_block_match:
        json_str = code_block_match.group(1).strip()
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        brace_start = json_str.find("{")
        brace_end = json_str.rfind("}")
        if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
            return json.loads(json_str[brace_start : brace_end + 1])
        raise ValueError(f"无法从 LLM 响应中提取 JSON: {raw[:200]}")


def llm_call_ollama(
    system: str,
    user: str,
    schema: dict[str, Any],
    ollama_base_url: str,
    model: str,
    timeout: float = 60.0,
) -> dict[str, Any]:
    """Call Ollama /api/chat to obtain structured JSON output."""
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0.1},
        }
    ).encode("utf-8")
    url = f"{ollama_base_url.rstrip('/')}/api/chat"
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    raw = body.get("message", {}).get("content", "")
    if not raw:
        raise RuntimeError("Ollama 返回空内容")
    return _extract_json_object(raw)


def llm_call_openai(
    system: str,
    user: str,
    schema: dict[str, Any],
    base_url: str,
    model: str,
    api_key: str = "",
    timeout: float = 120.0,
    enable_thinking: bool | None = None,
) -> dict[str, Any]:
    """Call the OpenAI-compatible API to obtain structured JSON output."""
    from openai import OpenAI

    schema_desc = json.dumps(schema, ensure_ascii=False, indent=2)
    enhanced_system = (
        f"{system}\n\n"
        f"你必须严格按照以下 JSON Schema 输出，不要遗漏任何 required 字段：\n"
        f"```json\n{schema_desc}\n```\n\n"
        f"只输出 JSON，不要添加任何解释文字。"
    )

    client = OpenAI(base_url=base_url, api_key=api_key or "dummy", timeout=timeout)
    create_kwargs: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": enhanced_system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
    }
    if enable_thinking is not None:
        create_kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": enable_thinking}}
    with suppress_token_usage():
        response = client.chat.completions.create(**create_kwargs)
    raw = response.choices[0].message.content
    if not raw:
        raise RuntimeError("OpenAI API 返回空内容")

    result = _extract_json_object(raw)
    result["_raw_response"] = response
    return result


def llm_call(
    system: str,
    user: str,
    schema: dict[str, Any],
    base_url: str,
    model: str,
    provider: str = "ollama",
    api_key: str = "",
    max_retries: int = 3,
    timeout: float | None = None,
    enable_thinking: bool | None = None,
) -> dict[str, Any]:
    """Unified LLM call entry point; dispatches to Ollama or OpenAI based on provider, with retries."""
    last_error = None
    for attempt in range(max_retries):
        try:
            if provider == "openai":
                return llm_call_openai(
                    system,
                    user,
                    schema,
                    base_url,
                    model,
                    api_key,
                    timeout=timeout or 120.0,
                    enable_thinking=enable_thinking,
                )
            return llm_call_ollama(
                system,
                user,
                schema,
                base_url,
                model,
                timeout=timeout or 60.0,
            )
        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = (2**attempt) * 0.5
                logger.warning(
                    "LLM 调用失败 (尝试 %d/%d): %s，%.1fs 后重试",
                    attempt + 1,
                    max_retries,
                    e,
                    wait_time,
                )
                time.sleep(wait_time)
    raise last_error
