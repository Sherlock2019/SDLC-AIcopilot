"""Adapters for hosted and local model providers.

Nothing here is imported or called while MOCK_AI=true. SDKs are imported lazily so the lab
installs and runs without them (see backend/requirements-providers.txt).

Status: the mock provider is what the test-suite and CI exercise. These adapters follow each
vendor's documented request shape but need your own credentials to be verified end to end.
"""
from __future__ import annotations

import os
import time

import httpx

from .base import LLMResponse, ProviderError

TIMEOUT = httpx.Timeout(120.0, connect=10.0)
MAX_TOKENS = 16000


def _require(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise ProviderError(f"{name} is not set.")
    return value


def _model(configured: str, env_name: str = "AI_MODEL") -> str:
    model = configured or os.environ.get(env_name, "")
    if not model:
        raise ProviderError(f"Set {env_name} to the model id you want to use with this provider.")
    return model


def _post(url: str, headers: dict, body: dict) -> dict:
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise ProviderError(f"Network error calling provider: {exc}") from None
    if response.status_code >= 400:
        raise ProviderError(f"Provider returned HTTP {response.status_code}: {response.text[:300]}")
    return response.json()


class _Timed:
    def __enter__(self):
        self.started = time.perf_counter()
        return self

    def __exit__(self, *_):
        self.ms = int((time.perf_counter() - self.started) * 1000)


class AnthropicProvider:
    """Anthropic models through the official Anthropic SDK. `AI_MODEL` is the model id."""

    name = "anthropic"

    def default_model(self) -> str:
        return os.environ.get("AI_MODEL", "")

    def _client(self):
        try:
            import anthropic
        except ImportError:
            raise ProviderError("Install the Anthropic SDK: pip install -r requirements-providers.txt") from None
        return anthropic.Anthropic()

    def _create(self, client, model: str, system: str, prompt: str):
        # Server-side refusal fallback lets a declined request be re-routed instead of failing the stage.
        return client.beta.messages.create(
            model=model, max_tokens=MAX_TOKENS, system=system,
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
            messages=[{"role": "user", "content": prompt}],
        )

    def complete(self, *, system, prompt, task, payload, model="", prompt_version="v2") -> LLMResponse:
        client, model = self._client(), _model(model)  # raises a clear error if the SDK is missing
        import anthropic
        with _Timed() as timer:
            try:
                message = self._create(client, model, system, prompt)
            except anthropic.RateLimitError as exc:
                raise ProviderError(f"Anthropic rate limit: {exc}") from None
            except anthropic.APIStatusError as exc:
                raise ProviderError(f"Anthropic API error {exc.status_code}: {exc.message}") from None
            except anthropic.APIConnectionError as exc:
                raise ProviderError(f"Could not reach the Anthropic API: {exc}") from None
        if message.stop_reason == "refusal":
            raise ProviderError("The model declined this request (stop_reason=refusal).")
        text = "".join(block.text for block in message.content if block.type == "text")
        notes = ["Output truncated at max_tokens."] if message.stop_reason == "max_tokens" else []
        return LLMResponse(text, self.name, message.model, message.usage.input_tokens,
                           message.usage.output_tokens, timer.ms, notes=notes)


class BedrockProvider(AnthropicProvider):
    """Anthropic models on Amazon Bedrock through the SDK's Bedrock client. `AI_MODEL` is the
    Bedrock model id. Credentials come from the AWS chain."""

    name = "bedrock"

    def _client(self):
        try:
            from anthropic import AnthropicBedrockMantle
        except ImportError:
            raise ProviderError("Install the Anthropic SDK: pip install -r requirements-providers.txt") from None
        return AnthropicBedrockMantle(aws_region=_require("AWS_REGION"))

    def _create(self, client, model: str, system: str, prompt: str):
        return client.messages.create(model=model, max_tokens=MAX_TOKENS, system=system,
                                      messages=[{"role": "user", "content": prompt}])


class _ChatCompletionsProvider:
    """Shared shape for OpenAI-compatible chat completion endpoints."""

    name = "openai-compatible"

    def default_model(self) -> str:
        return os.environ.get("AI_MODEL", "")

    def _endpoint(self, model: str) -> tuple[str, dict]:
        raise NotImplementedError

    def complete(self, *, system, prompt, task, payload, model="", prompt_version="v2") -> LLMResponse:
        model = _model(model)
        url, headers = self._endpoint(model)
        body = {"model": model, "messages": [{"role": "system", "content": system},
                                             {"role": "user", "content": prompt}]}
        with _Timed() as timer:
            data = _post(url, headers, body)
        usage = data.get("usage") or {}
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Unexpected response shape from provider.") from None
        return LLMResponse(text, self.name, data.get("model", model), usage.get("prompt_tokens", 0),
                           usage.get("completion_tokens", 0), timer.ms)


class OpenAIProvider(_ChatCompletionsProvider):
    name = "openai"

    def _endpoint(self, model):
        base = os.environ.get("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        return f"{base}/chat/completions", {"Authorization": f"Bearer {_require('OPENAI_API_KEY')}"}


class AzureOpenAIProvider(_ChatCompletionsProvider):
    """`AI_MODEL` is the Azure deployment name."""

    name = "azure"

    def _endpoint(self, model):
        endpoint = _require("AZURE_OPENAI_ENDPOINT").rstrip("/")
        version = _require("AZURE_OPENAI_API_VERSION")
        return (f"{endpoint}/openai/deployments/{model}/chat/completions?api-version={version}",
                {"api-key": _require("AZURE_OPENAI_API_KEY")})


class HuggingFaceProvider(_ChatCompletionsProvider):
    name = "huggingface"

    def _endpoint(self, model):
        base = os.environ.get("HF_BASE_URL", "https://router.huggingface.co/v1").rstrip("/")
        return f"{base}/chat/completions", {"Authorization": f"Bearer {_require('HF_TOKEN')}"}


class GeminiProvider:
    name = "gemini"

    def default_model(self) -> str:
        return os.environ.get("AI_MODEL", "")

    def complete(self, *, system, prompt, task, payload, model="", prompt_version="v2") -> LLMResponse:
        model = _model(model)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        body = {"systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": prompt}]}]}
        with _Timed() as timer:
            data = _post(url, {"x-goog-api-key": _require("GOOGLE_API_KEY")}, body)
        try:
            text = "".join(part.get("text", "") for part in data["candidates"][0]["content"]["parts"])
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Unexpected response shape from Gemini.") from None
        usage = data.get("usageMetadata") or {}
        return LLMResponse(text, self.name, model, usage.get("promptTokenCount", 0),
                           usage.get("candidatesTokenCount", 0), timer.ms)


class OllamaProvider:
    """Local models. No key, no data leaves the machine."""

    name = "ollama"

    def default_model(self) -> str:
        return os.environ.get("AI_MODEL", "")

    def complete(self, *, system, prompt, task, payload, model="", prompt_version="v2") -> LLMResponse:
        model = _model(model)
        host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        body = {"model": model, "stream": False, "format": "json",
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}]}
        with _Timed() as timer:
            data = _post(f"{host}/api/chat", {}, body)
        text = (data.get("message") or {}).get("content", "")
        return LLMResponse(text, self.name, model, data.get("prompt_eval_count", 0), data.get("eval_count", 0),
                           timer.ms)
