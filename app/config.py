"""Config from .env (see .env.example). No secrets in code or git."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())


_load_env()

SENDER_NAME = os.environ.get("SENDER_NAME", "")
SENDER_PHONE = os.environ.get("SENDER_PHONE", "")
GMAIL_USER = os.environ.get("GMAIL_USER", "")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "465"))
# seconds between sends so ~100 emails don't look like a spam burst
SEND_INTERVAL_SECONDS = int(os.environ.get("SEND_INTERVAL_SECONDS", "20"))
