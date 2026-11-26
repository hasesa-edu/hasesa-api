"""The AI provider: any OpenAI-compatible chat completions API, streamed."""

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass

import httpx

from hasesa_api.config import get_settings

log = logging.getLogger(__name__)


class ProviderUnavailable(Exception):
    pass


@dataclass
class OpenStream:
    """A provider response whose body hasn't been read yet."""

    client: httpx.AsyncClient
    response: httpx.Response

    async def deltas(self) -> AsyncIterator[str]:
        """The answer's text, piece by piece, until the provider says [DONE]."""
        async for line in self.response.aiter_lines():
            line = line.strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                return
            try:
                delta = json.loads(data)["choices"][0]["delta"].get("content")
            except (ValueError, KeyError, IndexError, TypeError, AttributeError):
                continue  # partial or unrelated chunk
            if delta:
                yield delta

    async def close(self) -> None:
        await self.response.aclose()
        await self.client.aclose()


async def open_stream(system_prompt: str, messages: list[dict[str, str]]) -> OpenStream:
    """Start a streamed completion. Raises ProviderUnavailable before any text
    is sent, so the caller can refund the message and answer with an error."""
    s = get_settings()
    if not s.ai_api_key:
        raise ProviderUnavailable("AI_API_KEY not configured")
    body: dict = {
        "model": s.ai_model,
        "stream": True,
        "temperature": 0.4,
        "max_tokens": 800,
        "messages": [{"role": "system", "content": system_prompt}, *messages],
    }
    if s.ai_reasoning_effort:
        body["reasoning_effort"] = s.ai_reasoning_effort
    client = httpx.AsyncClient(timeout=httpx.Timeout(60, connect=10))
    try:
        req = client.build_request(
            "POST",
            f"{s.ai_base_url.rstrip('/')}/chat/completions",
            json=body,
            headers={"Authorization": f"Bearer {s.ai_api_key}"},
        )
        res = await client.send(req, stream=True)
    except httpx.HTTPError as e:
        await client.aclose()
        log.error("AI provider request failed: %s", e)
        raise ProviderUnavailable(str(e)) from e
    if res.status_code != 200:
        # Log upstream detail here; never relay it to the student.
        text = (await res.aread()).decode(errors="replace")[:300]
        await res.aclose()
        await client.aclose()
        log.error("AI provider error %s: %s", res.status_code, text)
        raise ProviderUnavailable(f"status {res.status_code}")
    return OpenStream(client, res)
