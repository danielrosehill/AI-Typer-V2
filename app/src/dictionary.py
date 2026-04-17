"""Custom dictionary — post-processing substitutions for transcriptions.

Common transcription errors (names, jargon, homophones the model consistently
mishears) are fixed here rather than in the system prompt. A JSON file stores
a list of entries; `apply_substitutions` runs them against the final text
after the API response (and after any review pass).

Schema (list of entries):
    {"from": "wrong", "to": "right", "whole_word": true, "case_sensitive": false}
"""

import csv
import json
import logging
import re
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)

DICTIONARY_FILE = Path.home() / ".config" / "ai-typer-v2" / "dictionary.json"


class DictEntry(TypedDict):
    from_: str
    to: str
    whole_word: bool
    case_sensitive: bool


def load_entries() -> list[dict]:
    """Load dictionary entries from disk. Returns [] if missing or malformed."""
    if not DICTIONARY_FILE.exists():
        return []
    try:
        with open(DICTIONARY_FILE) as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        result = []
        for entry in data:
            if not isinstance(entry, dict):
                continue
            frm = str(entry.get("from", "")).strip()
            to = str(entry.get("to", ""))
            if not frm:
                continue
            result.append({
                "from": frm,
                "to": to,
                "whole_word": bool(entry.get("whole_word", True)),
                "case_sensitive": bool(entry.get("case_sensitive", False)),
            })
        return result
    except Exception:
        logger.exception("Failed to load dictionary")
        return []


def save_entries(entries: list[dict]) -> None:
    """Save dictionary entries to disk."""
    DICTIONARY_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DICTIONARY_FILE, "w") as f:
        json.dump(entries, f, indent=2)


def _coerce_bool(value, default: bool) -> bool:
    """Parse truthy/falsy values from CSV strings or Python objects."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    s = str(value).strip().lower()
    if s in ("1", "true", "yes", "y", "t"):
        return True
    if s in ("0", "false", "no", "n", "f", ""):
        return False
    return default


def export_csv(entries: list[dict], path: Path) -> None:
    """Write entries to a CSV file. Header: from,to,whole_word,case_sensitive."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["from", "to", "whole_word", "case_sensitive"])
        for e in entries:
            writer.writerow([
                e.get("from", ""),
                e.get("to", ""),
                "true" if e.get("whole_word", True) else "false",
                "true" if e.get("case_sensitive", False) else "false",
            ])


def export_json(entries: list[dict], path: Path) -> None:
    """Write entries to a JSON file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entries, f, indent=2)


def import_csv(path: Path) -> list[dict]:
    """Read entries from a CSV file. Expects header with at least 'from' and 'to'.

    Column names are case-insensitive. Missing `whole_word` defaults to true;
    missing `case_sensitive` defaults to false.
    """
    entries = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            return []
        # Normalize header names to lowercase for lookup
        field_map = {name.lower().strip(): name for name in reader.fieldnames}
        from_key = field_map.get("from") or field_map.get("mistaken") or field_map.get("spoken")
        to_key = field_map.get("to") or field_map.get("correct") or field_map.get("written")
        if not from_key or not to_key:
            raise ValueError("CSV must have 'from' and 'to' columns")
        whole_key = field_map.get("whole_word")
        case_key = field_map.get("case_sensitive")
        for row in reader:
            frm = (row.get(from_key) or "").strip()
            if not frm:
                continue
            entries.append({
                "from": frm,
                "to": row.get(to_key) or "",
                "whole_word": _coerce_bool(row.get(whole_key) if whole_key else None, True),
                "case_sensitive": _coerce_bool(row.get(case_key) if case_key else None, False),
            })
    return entries


def import_json(path: Path) -> list[dict]:
    """Read entries from a JSON file (same schema as the native store)."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError("JSON file must contain a list of entries")
    entries = []
    for item in data:
        if not isinstance(item, dict):
            continue
        frm = str(item.get("from", "")).strip()
        if not frm:
            continue
        entries.append({
            "from": frm,
            "to": str(item.get("to", "")),
            "whole_word": _coerce_bool(item.get("whole_word"), True),
            "case_sensitive": _coerce_bool(item.get("case_sensitive"), False),
        })
    return entries


def apply_substitutions(text: str, entries: list[dict] | None = None) -> str:
    """Apply dictionary substitutions to text.

    Uses regex with optional word boundaries and case-insensitive matching.
    `from` is treated as a literal string (escaped before regex compilation).
    """
    if not text:
        return text
    if entries is None:
        entries = load_entries()
    if not entries:
        return text

    for entry in entries:
        frm = entry.get("from", "")
        to = entry.get("to", "")
        if not frm:
            continue
        pattern = re.escape(frm)
        if entry.get("whole_word", True):
            pattern = rf"\b{pattern}\b"
        flags = 0 if entry.get("case_sensitive", False) else re.IGNORECASE
        try:
            text = re.sub(pattern, to, text, flags=flags)
        except re.error:
            logger.warning("Skipping malformed dictionary entry: %r", entry)
            continue
    return text
