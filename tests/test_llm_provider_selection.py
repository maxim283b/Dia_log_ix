from __future__ import annotations

from app.config import Settings
from app.llm.providers import OllamaLLMProvider, OpenAICompatibleLLMProvider
from app.telegram.bot import build_llm_provider


def test_build_llm_provider_selects_ollama_provider():
    provider = build_llm_provider(
        Settings(
            llm_provider="ollama",
            llm_base_url="https://ollama.com/api",
            llm_api_key="test-key",
            llm_model="gpt-oss:20b",
        )
    )

    assert isinstance(provider, OllamaLLMProvider)


def test_build_llm_provider_defaults_to_openai_compatible_provider():
    provider = build_llm_provider(
        Settings(
            llm_provider="openai",
            llm_base_url="https://api.mistral.ai/v1",
            llm_api_key="test-key",
            llm_model="mistral-small-latest",
        )
    )

    assert isinstance(provider, OpenAICompatibleLLMProvider)
