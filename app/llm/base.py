from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class LLMResponse:
    text: str
    raw: dict | None = None


class LLMProvider(Protocol):
    async def generate_text(self, *, system: str, prompt: str, timeout_seconds: int | None = None) -> LLMResponse: ...

    async def generate_json(self, *, system: str, prompt: str, timeout_seconds: int | None = None) -> dict: ...
