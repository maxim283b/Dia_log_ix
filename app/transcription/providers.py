from __future__ import annotations

import asyncio
import base64
import json
from urllib import request

from app.transcription.base import TranscriptionResult


class MockTranscriptionProvider:
    async def transcribe(self, *, audio_bytes: bytes, filename: str, mime_type: str | None = None) -> TranscriptionResult:
        return TranscriptionResult(text=f"[mock transcription for {filename}, {len(audio_bytes)} bytes]")


class SimpleHTTPTranscriptionProvider:
    def __init__(self, base_url: str, api_key: str, model: str, timeout_seconds: int = 120) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds

    async def transcribe(self, *, audio_bytes: bytes, filename: str, mime_type: str | None = None) -> TranscriptionResult:
        payload = {
            "model": self.model,
            "filename": filename,
            "mime_type": mime_type,
            "audio_b64": base64.b64encode(audio_bytes).decode("ascii"),
        }
        data = await asyncio.to_thread(self._post_json, "/transcriptions", payload)
        return TranscriptionResult(text=data.get("text", ""), raw=data)

    def _post_json(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            f"{self.base_url}{path}",
            data=body,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        with request.urlopen(req, timeout=self.timeout_seconds) as resp:
            return json.loads(resp.read().decode("utf-8"))


class FasterWhisperTranscriptionProvider:
    def __init__(self, model: str = "small") -> None:
        self.model = model
        self._model = None

    async def transcribe(self, *, audio_bytes: bytes, filename: str, mime_type: str | None = None) -> TranscriptionResult:
        from pathlib import Path
        import tempfile

        try:
            from faster_whisper import WhisperModel
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("faster-whisper is not installed") from exc

        if self._model is None:
            self._model = WhisperModel(self.model)
        with tempfile.TemporaryDirectory(prefix="digestbot-whisper-") as tmpdir:
            path = Path(tmpdir) / filename
            path.write_bytes(audio_bytes)
            segments, info = self._model.transcribe(str(path))
            text = " ".join(segment.text for segment in segments).strip()
            return TranscriptionResult(text=text, raw={"language": getattr(info, "language", None)})
