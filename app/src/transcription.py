"""Transcription API client using OpenRouter with multimodal models."""

import base64
import logging
import re
from dataclasses import dataclass
from typing import Optional

try:
    from openai import OpenAI
    OPENAI_SDK_AVAILABLE = True
except ImportError:
    OpenAI = None
    OPENAI_SDK_AVAILABLE = False

logger = logging.getLogger(__name__)

# Patterns that match AI preamble lines (case-insensitive).
_PREAMBLE_PATTERNS = [
    re.compile(r"^here(?:'s| is| are)\b", re.IGNORECASE),
    re.compile(r"^sure[,!.]?\s", re.IGNORECASE),
    re.compile(r"^certainly[,!.]?\s", re.IGNORECASE),
    re.compile(r"^of course[,!.]?\s", re.IGNORECASE),
    re.compile(r"^i'?d be (?:happy|glad|delighted) to\b", re.IGNORECASE),
    re.compile(r"^below is\b", re.IGNORECASE),
    re.compile(r"^the (?:transcri(?:bed|ption)|cleaned|polished|edited)\b", re.IGNORECASE),
    re.compile(r"^i'?ve (?:transcribed|cleaned|polished)\b", re.IGNORECASE),
    re.compile(r"^(?:okay|ok)[,!.]?\s+here\b", re.IGNORECASE),
    re.compile(r"^let me\b", re.IGNORECASE),
    re.compile(r"^absolutely[,!.]?\s", re.IGNORECASE),
]


def strip_ai_preamble(text: str) -> str:
    """Remove AI preamble/commentary from the start of a response."""
    if not text:
        return text

    stripped = text.lstrip()
    if not stripped:
        return text

    first_newline = stripped.find("\n")
    first_line = stripped[:first_newline] if first_newline != -1 else stripped

    if first_newline == -1 and not first_line.rstrip().endswith(":"):
        return text

    for pattern in _PREAMBLE_PATTERNS:
        if pattern.search(first_line):
            remainder = stripped[first_newline + 1:] if first_newline != -1 else ""
            result = remainder.lstrip("\n")
            if result:
                return result
            return text

    return text


@dataclass
class TranscriptionResult:
    """Result from transcription API including usage data."""
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    actual_cost: Optional[float] = None
    generation_id: Optional[str] = None


class OpenRouterClient:
    """OpenRouter API client for audio transcription."""

    OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"

    _shared_client = None
    _shared_client_key: str = ""

    def __init__(self, api_key: str, model: str = "google/gemini-3-flash-preview"):
        self.api_key = api_key
        self.model = model

    def _get_client(self):
        if (OpenRouterClient._shared_client is not None
                and OpenRouterClient._shared_client_key == self.api_key):
            return OpenRouterClient._shared_client
        if not OPENAI_SDK_AVAILABLE:
            raise ImportError("openai package not installed")
        OpenRouterClient._shared_client = OpenAI(
            api_key=self.api_key,
            base_url=self.OPENROUTER_BASE_URL,
        )
        OpenRouterClient._shared_client_key = self.api_key
        return OpenRouterClient._shared_client

    def transcribe(self, audio_data: bytes, prompt: str) -> TranscriptionResult:
        """Transcribe audio using multimodal model."""
        client = self._get_client()
        audio_b64 = base64.b64encode(audio_data).decode("utf-8")

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "[audio]"},
                        {
                            "type": "input_audio",
                            "input_audio": {"data": audio_b64, "format": "wav"}
                        }
                    ]
                }
            ],
            extra_body={"usage": {"include": True}},
        )

        input_tokens = 0
        output_tokens = 0
        actual_cost = None
        generation_id = None

        if hasattr(response, 'id') and response.id:
            generation_id = response.id
        if hasattr(response, 'usage') and response.usage:
            input_tokens = getattr(response.usage, 'prompt_tokens', 0) or 0
            output_tokens = getattr(response.usage, 'completion_tokens', 0) or 0
            if hasattr(response.usage, 'cost'):
                actual_cost = getattr(response.usage, 'cost', None)

        return TranscriptionResult(
            text=strip_ai_preamble(response.choices[0].message.content),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            actual_cost=actual_cost,
            generation_id=generation_id,
        )

    def review_text(self, text: str, review_prompt: str) -> TranscriptionResult:
        """Second-pass review of transcription (text-only, no audio)."""
        client = self._get_client()

        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": review_prompt},
                {"role": "user", "content": text}
            ],
            extra_body={"usage": {"include": True}},
        )

        input_tokens = 0
        output_tokens = 0
        actual_cost = None
        generation_id = None

        if hasattr(response, 'id') and response.id:
            generation_id = response.id
        if hasattr(response, 'usage') and response.usage:
            input_tokens = getattr(response.usage, 'prompt_tokens', 0) or 0
            output_tokens = getattr(response.usage, 'completion_tokens', 0) or 0
            if hasattr(response.usage, 'cost'):
                actual_cost = getattr(response.usage, 'cost', None)

        return TranscriptionResult(
            text=strip_ai_preamble(response.choices[0].message.content),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            actual_cost=actual_cost,
            generation_id=generation_id,
        )


def get_client(api_key: str, model: str) -> OpenRouterClient:
    """Factory function to get transcription client."""
    return OpenRouterClient(api_key, model)
