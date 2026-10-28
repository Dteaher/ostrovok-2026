"""Bounded JSON model requests, retrying only transient provider failures."""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from contextvars import ContextVar

import httpx

from app.llm_config import LLMConfig, parse_completion, strict_object_schema
from app.request_budget import deadline_or

logger = logging.getLogger(__name__)
shared_provider_client = ContextVar("shared_provider_client", default=None)


@asynccontextmanager
async def provider_session():
    """Reuse an app/benchmark-owned pool, never a connection from another loop."""
    existing = shared_provider_client.get()
    if existing is not None:
        yield existing
        return
    config = LLMConfig.from_env()
    async with httpx.AsyncClient(timeout=config.timeout, follow_redirects=False,
                                 trust_env=config.trust_env) as client:
        token = shared_provider_client.set(client)
        try:
            yield client
        finally:
            shared_provider_client.reset(token)


async def model_json(messages, *, deadline, attempts=2, schema=None, validator=None,
                     output_schema=None, schema_name="response", retry_http_errors=True):
    config = LLMConfig.from_env()
    if output_schema is None and schema is not None and config.structured_output:
        output_schema = strict_object_schema(schema.model_json_schema())
    deadline = min(deadline, deadline_or(config.timeout))
    messages = list(messages)
    for attempt in range(min(attempts, 2)):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("Agent deadline reached")
        try:
            async with asyncio.timeout(remaining):
                async with provider_session() as client:
                    response = await client.post(config.base_url + "/chat/completions",
                        headers={"Authorization": "Bearer " + config.api_key},
                        json=config.request_body(messages, output_schema=output_schema,
                                                 schema_name=schema_name),
                        timeout=httpx.Timeout(min(config.timeout, remaining),
                                              connect=min(3, remaining)))
                    if retry_http_errors and response.status_code in {429, 502, 503, 504} and attempt == 0 and attempts > 1:
                        try:
                            delay = min(max(float(response.headers.get("Retry-After", "0.2")), 0), 1)
                        except ValueError:
                            delay = 0.2
                        if time.monotonic() + delay >= deadline:
                            raise TimeoutError("Agent retry deadline reached")
                        await asyncio.sleep(delay)
                        continue
                    response.raise_for_status()
                    result = parse_completion(response.json())
                    if schema is not None:
                        schema.model_validate(result)
                    if validator is not None:
                        validator(result)
                    return result
        except ValueError:
            if attempt == 0 and attempts > 1 and schema is not None:
                fields = ", ".join(schema.model_fields)
                messages.append({"role": "user", "content": "The previous output violated the required JSON schema. Return one valid JSON object with ONLY these keys: " + fields + ". No extra keys, commentary or markdown. Use allowed enum values and exact evidence IDs. Schema: " + str(schema.model_json_schema())})
                continue
            logger.info("Agent response schema validation failed")
            raise
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError):
            # A failed handshake/stale pooled socket may recover. This never
            # retries authorization/balance errors or extends the turn budget.
            if attempt == 0 and attempts > 1 and deadline - time.monotonic() > 1:
                continue
            raise
        except (httpx.HTTPError, KeyError, IndexError, TypeError, TimeoutError) as exc:
            # No response bodies, user text, headers or credentials in logs.
            logger.info("Agent provider call failed: %s", type(exc).__name__)
            raise
    raise TimeoutError("Agent request budget exhausted")
