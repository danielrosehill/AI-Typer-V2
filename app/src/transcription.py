"""Transcription API client using OpenRouter (OpenAI-compatible API)."""

import base64
import logging
import re
from dataclasses import dataclass
from typing import Optional

import requests

logger = logging.getLogger(__name__)

OPENROUTER_API_URL = "https://openrouter.ai/api/v1/chat/completions"

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
    This function detects paragraph boundaries and inserts blank lines.
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

        # Current line is a list item, heading, or code block — keep as-is
        if curr.startswith(("-", "*", "#", ">", "`")):
            result.append(lines[i])
            continue
        # Numbered list items
        if len(curr) > 1 and curr[0].isdigit() and curr[1] in ".)":
            result.append(lines[i])
            continue

        needs_break = False

        # Previous line is a heading (markdown # or short standalone line)
        if prev.startswith("#"):
            needs_break = True
        # Short previous line (title/heading-like) followed by longer content
        elif len(prev) < 60 and len(curr) > 60 and not prev[-1] in ",;:":
            needs_break = True
        # Previous line ends with terminal punctuation, next starts uppercase
        elif prev[-1] in ".?!\"')" and curr[0].isupper():
            needs_break = True

        if needs_break:
            result.append("")
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


class OpenRouterClient:
    """OpenRouter API client for audio transcription."""

    def __init__(self, api_key: str, model: str = "google/gemini-3.1-flash-lite-preview"):
        self.api_key = api_key
        self.model = model
        self._session: Optional[requests.Session] = None

    def _get_session(self) -> requests.Session:
        if self._session is None:
            self._session = requests.Session()
            self._session.headers.update({
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            })
        return self._session

    def transcribe(self, audio_data: bytes, prompt: str) -> TranscriptionResult:
        """Transcribe audio using OpenRouter multimodal model."""
        audio_b64 = base64.b64encode(audio_data).decode("utf-8")

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": prompt,
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_b64,
                                "format": "mp3",
                            },
                        },
                    ],
                },
            ],
        }

        session = self._get_session()
        response = session.post(OPENROUTER_API_URL, json=payload, timeout=120)
        response.raise_for_status()
        data = response.json()

        text = data["choices"][0]["message"]["content"]
        input_tokens = data.get("usage", {}).get("prompt_tokens", 0)
        output_tokens = data.get("usage", {}).get("completion_tokens", 0)

        return TranscriptionResult(
            text=normalize_paragraph_spacing(strip_ai_preamble(text)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    def review_text(self, text: str, review_prompt: str) -> TranscriptionResult:
        """Second-pass review of transcription (text-only, no audio)."""
        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": review_prompt,
                },
                {
                    "role": "user",
                    "content": text,
                },
            ],
        }

        session = self._get_session()
        response = session.post(OPENROUTER_API_URL, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()

        text = data["choices"][0]["message"]["content"]
        input_tokens = data.get("usage", {}).get("prompt_tokens", 0)
        output_tokens = data.get("usage", {}).get("completion_tokens", 0)

        return TranscriptionResult(
            text=normalize_paragraph_spacing(strip_ai_preamble(text)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )


def get_client(api_key: str, model: str) -> OpenRouterClient:
    """Factory function to get transcription client."""
    return OpenRouterClient(api_key, model)
