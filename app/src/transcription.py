"""Transcription API client using Google Gemini directly."""

import logging
import re
from dataclasses import dataclass
from typing import Optional

try:
    from google import genai
    from google.genai import types
    GENAI_AVAILABLE = True
except ImportError:
    genai = None
    types = None
    GENAI_AVAILABLE = False

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


def normalize_paragraph_spacing(text: str) -> str:
    """Ensure blank lines between paragraphs.

    LLMs often use single newlines where they intended paragraph breaks.
    If a line ends with terminal punctuation and the next starts with a
    capital letter, insert a blank line between them.
    """
    if not text or "\n" not in text:
        return text

    lines = text.split("\n")
    result = [lines[0]]

    for i in range(1, len(lines)):
        prev = lines[i - 1].rstrip()
        curr = lines[i].lstrip()

        # Already a blank line, or current/prev line is empty — keep as-is
        if not prev or not curr:
            result.append(lines[i])
            continue

        # Skip normalization for list items, headings, code blocks
        if curr.startswith(("-", "*", "#", ">", "`", "1", "2", "3", "4", "5", "6", "7", "8", "9")):
            result.append(lines[i])
            continue

        # Prev line ends with sentence-ending punctuation, next starts uppercase
        if prev[-1] in ".?!\"'" and curr[0].isupper():
            result.append("")  # Insert blank line
            result.append(lines[i])
        else:
            result.append(lines[i])

    return "\n".join(result)


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


class GeminiClient:
    """Google Gemini API client for audio transcription."""

    _shared_client = None
    _shared_client_key: str = ""

    def __init__(self, api_key: str, model: str = "gemini-3.1-flash-lite-preview"):
        self.api_key = api_key
        self.model = model

    def _get_client(self):
        if (GeminiClient._shared_client is not None
                and GeminiClient._shared_client_key == self.api_key):
            return GeminiClient._shared_client
        if not GENAI_AVAILABLE:
            raise ImportError("google-genai package not installed — pip install google-genai")
        GeminiClient._shared_client = genai.Client(api_key=self.api_key)
        GeminiClient._shared_client_key = self.api_key
        return GeminiClient._shared_client

    def transcribe(self, audio_data: bytes, prompt: str) -> TranscriptionResult:
        """Transcribe audio using Gemini multimodal model."""
        client = self._get_client()

        response = client.models.generate_content(
            model=self.model,
            config={"system_instruction": prompt},
            contents=[
                types.Part.from_bytes(data=audio_data, mime_type="audio/wav"),
            ],
        )

        input_tokens = 0
        output_tokens = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
            output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0

        return TranscriptionResult(
            text=normalize_paragraph_spacing(strip_ai_preamble(response.text)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def review_text(self, text: str, review_prompt: str) -> TranscriptionResult:
        """Second-pass review of transcription (text-only, no audio)."""
        client = self._get_client()

        response = client.models.generate_content(
            model=self.model,
            config={"system_instruction": review_prompt},
            contents=text,
        )

        input_tokens = 0
        output_tokens = 0
        if hasattr(response, 'usage_metadata') and response.usage_metadata:
            input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
            output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0

        return TranscriptionResult(
            text=normalize_paragraph_spacing(strip_ai_preamble(response.text)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def get_client(api_key: str, model: str) -> GeminiClient:
    """Factory function to get transcription client."""
    return GeminiClient(api_key, model)
