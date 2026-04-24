from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from app.transcription.service import TelegramMediaTranscriber


@dataclass
class _FakeFile:
    file_path: str = "video_note.mp4"


class _FakeBot:
    async def get_file(self, file_id: str) -> _FakeFile:
        return _FakeFile(file_path=f"{file_id}.mp4")

    async def download(self, file: _FakeFile, destination: Path) -> None:
        destination.write_bytes(b"fake-mp4-bytes")


class _FakeProvider:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def transcribe(self, *, audio_bytes: bytes, filename: str, mime_type: str | None = None):
        self.calls.append(
            {"audio_bytes": audio_bytes, "filename": filename, "mime_type": mime_type}
        )
        return type("Result", (), {"text": "transcribed video note", "raw": {}})()


@pytest.mark.asyncio
async def test_video_note_transcription_without_ffmpeg(monkeypatch):
    provider = _FakeProvider()
    bot = _FakeBot()
    transcriber = TelegramMediaTranscriber(bot, provider)
    monkeypatch.setattr("app.transcription.service.shutil.which", lambda _: None)

    message = type(
        "Message",
        (),
        {"file_id": "abc123", "message_type": "video_note", "transcribed_text": None},
    )()

    result = await transcriber.transcribe_message(message)

    assert result == "transcribed video note"
    assert provider.calls
    assert provider.calls[0]["mime_type"] == "video/mp4"
    assert provider.calls[0]["audio_bytes"] == b"fake-mp4-bytes"

