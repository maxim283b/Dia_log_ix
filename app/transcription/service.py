from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path
import subprocess
import tempfile
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from aiogram import Bot
    from aiogram.types import Message

from app.transcription.base import TranscriptionProvider

logger = logging.getLogger(__name__)


class TelegramMediaTranscriber:
    def __init__(self, bot: "Bot", provider: TranscriptionProvider) -> None:
        self.bot = bot
        self.provider = provider

    async def transcribe_message(self, message: "Message") -> str | None:
        if not getattr(message, "file_id", None):
            return None
        message_type = getattr(message, "message_type", "audio")
        with tempfile.TemporaryDirectory(prefix="digestbot-media-") as tmpdir:
            tmpdir_path = Path(tmpdir)
            downloaded = await self._download(message.file_id, tmpdir_path / self._target_filename(message))
            source_path = downloaded
            if message_type == "video_note":
                converted = await asyncio.to_thread(self._convert_video_note, downloaded, tmpdir_path)
                if converted is None:
                    logger.warning("ffmpeg is unavailable; sending raw video_note bytes to transcription backend")
                else:
                    source_path = converted
            audio_bytes = source_path.read_bytes()
            result = await self.provider.transcribe(
                audio_bytes=audio_bytes,
                filename=source_path.name,
                mime_type=self._mime_type(message_type),
            )
            message.transcribed_text = result.text
            return result.text

    async def _download(self, file_id: str, destination: Path) -> Path:
        file = await self.bot.get_file(file_id)
        await self.bot.download(file, destination=destination)
        return destination

    def _target_filename(self, message: "Message") -> str:
        message_type = getattr(message, "message_type", "audio")
        if message_type == "voice":
            return f"{message.file_id}.ogg"
        if message_type == "video_note":
            return f"{message.file_id}.mp4"
        audio = getattr(message, "audio", None)
        file_name = getattr(audio, "file_name", None) or f"{message.file_id}.bin"
        return file_name

    def _mime_type(self, message_type: str) -> str | None:
        if message_type == "voice":
            return "audio/ogg"
        if message_type == "audio":
            return "audio/mpeg"
        if message_type == "video_note":
            return "video/mp4"
        return None

    def _convert_video_note(self, input_path: Path, tmpdir: Path) -> Path | None:
        if shutil.which("ffmpeg") is None:
            return None
        output_path = tmpdir / f"{input_path.stem}.wav"
        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(input_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(output_path),
        ]
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except FileNotFoundError:
            return None
        except subprocess.CalledProcessError as exc:
            logger.warning("ffmpeg conversion failed: %s", exc)
            return None
        return output_path
