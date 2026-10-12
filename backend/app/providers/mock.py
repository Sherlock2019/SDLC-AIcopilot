"""Deterministic mock provider (MOCK_AI=true).

It returns scripted, schema-valid answers per task so the whole lab runs offline and the same
way every time. Two knobs make evaluation meaningful without a real model:

  prompt_version  v1 = bare prompt with no retrieved context  -> plausible but unsafe output
                  v2 = grounded prompt with policy context     -> policy-compliant output
  model           mock-large = slower, pricier, complete
                  mock-small = faster, cheaper, misses one requirement

Token counts are computed from the real prompt and response text. Latency is modelled, not slept.
"""
import json

from ..core.tokens import count_tokens
from . import mock_tasks
from .base import LLMResponse, ProviderError

LATENCY = {"mock-large": (420, 11.0), "mock-small": (140, 3.5)}  # (base ms, ms per output token)


class MockProvider:
    name = "mock"

    def default_model(self) -> str:
        return "mock-large"

    def complete(self, *, system, prompt, task, payload, model="", prompt_version="v2") -> LLMResponse:
        model = model if model in LATENCY else self.default_model()
        handler = mock_tasks.TASKS.get(task)
        if handler is None:
            raise ProviderError(f"Mock provider has no script for task '{task}'.")
        text = json.dumps(handler(payload, prompt_version, model), ensure_ascii=False)
        tokens_in, tokens_out = count_tokens(system) + count_tokens(prompt), count_tokens(text)
        base, per_token = LATENCY[model]
        return LLMResponse(text, self.name, model, tokens_in, tokens_out, int(base + per_token * tokens_out),
                           simulated=True)
