"""Load ANTHROPIC_API_KEY from a .env file at the project root, if there is one.

Keeps local runs to a single command. Real environment variables always win, so
hosting platforms (Render, Docker) that inject the key are unaffected, and .env
is never committed.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def load_dotenv(path: Path | None = None) -> bool:
    """Returns True if a file was found and read."""
    env = path or ENV_FILE
    if not env.exists():
        return False
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return True


def credentials_present() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))
