"""Provider registry. MOCK_AI=true always wins, so the demo never needs a key."""
from ..config import settings
from .mock import MockProvider
from .real import (AnthropicProvider, AzureOpenAIProvider, BedrockProvider, GeminiProvider,
                   HuggingFaceProvider, OllamaProvider, OpenAIProvider)

PROVIDERS = {
    "mock": MockProvider,
    "anthropic": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "bedrock": BedrockProvider,
    "azure": AzureOpenAIProvider,
    "huggingface": HuggingFaceProvider,
    "ollama": OllamaProvider,
}

REQUIRES = {
    "mock": [], "anthropic": ["ANTHROPIC_API_KEY", "AI_MODEL"], "openai": ["OPENAI_API_KEY", "AI_MODEL"],
    "gemini": ["GOOGLE_API_KEY", "AI_MODEL"], "bedrock": ["AWS_REGION", "AI_MODEL"],
    "azure": ["AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_API_VERSION", "AI_MODEL"],
    "huggingface": ["HF_TOKEN", "AI_MODEL"], "ollama": ["AI_MODEL"],
}


def get_provider(name: str | None = None):
    name = name or settings.effective_provider
    if name not in PROVIDERS:
        raise ValueError(f"Unknown AI_PROVIDER '{name}'. Choose one of: {', '.join(PROVIDERS)}")
    return PROVIDERS[name]()


def provider_catalog() -> list[dict]:
    active = settings.effective_provider
    return [{"name": name, "active": name == active, "requires": REQUIRES[name],
             "verified_in_ci": name == "mock"} for name in PROVIDERS]
