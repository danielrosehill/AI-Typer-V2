"""Clipboard operations using wl-copy (Wayland) with fallback."""

import subprocess
import logging

logger = logging.getLogger(__name__)


def copy_to_clipboard(text: str) -> bool:
    """Copy text to clipboard. Returns True on success."""
    try:
        proc = subprocess.Popen(
            ["wl-copy"],
            stdin=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        proc.communicate(input=text.encode("utf-8"), timeout=5)
        return proc.returncode == 0
    except FileNotFoundError:
        # wl-copy not available, try xclip
        try:
            proc = subprocess.Popen(
                ["xclip", "-selection", "clipboard"],
                stdin=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            proc.communicate(input=text.encode("utf-8"), timeout=5)
            return proc.returncode == 0
        except FileNotFoundError:
            logger.error("No clipboard tool found (install wl-copy or xclip)")
            return False
    except Exception as e:
        logger.error(f"Clipboard error: {e}")
        return False
