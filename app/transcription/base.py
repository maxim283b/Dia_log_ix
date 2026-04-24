from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class TranscriptionResult:
    text: str
    raw: dict | None = None


class TranscriptionProvider(Protocol):
    async def transcribe(self, *, audio_bytes: bytes, filename: str, mime_type: str | None = None) -> TranscriptionResult: ...

