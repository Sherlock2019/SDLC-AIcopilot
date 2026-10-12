"""Model provider abstraction. Agents depend on this interface, never on a vendor SDK."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Protocol


class ProviderError(RuntimeError):
    pass


@dataclass
class LLMResponse:
    text: str
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    latency_ms: int = 0
    simulated: bool = False
    notes: list = field(default_factory=list)


class LLMProvider(Protocol):
    name: str

    def default_model(self) -> str: ...

    def complete(self, *, system: str, prompt: str, task: str, payload: dict, model: str = "",
                 prompt_version: str = "v2") -> LLMResponse: ...


def extract_json(text: str) -> dict:
    """Parse a JSON object out of model output. Model output is untrusted: this raises, never guesses."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        value = json.loads(cleaned)
    except ValueError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start == -1 or end <= start:
            raise ProviderError("Model did not return a JSON object.") from None
        try:
            value = json.loads(cleaned[start:end + 1])
        except ValueError as exc:
            raise ProviderError(f"Model returned invalid JSON: {exc}") from None
    if not isinstance(value, dict):
        raise ProviderError("Model returned JSON that is not an object.")
    return value
