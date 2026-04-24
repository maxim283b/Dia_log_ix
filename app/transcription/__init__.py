from app.transcription.base import TranscriptionProvider, TranscriptionResult
from app.transcription.providers import (
    FasterWhisperTranscriptionProvider,
    MockTranscriptionProvider,
    SimpleHTTPTranscriptionProvider,
)
from app.transcription.service import TelegramMediaTranscriber
