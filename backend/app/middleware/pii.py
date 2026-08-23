import logging
import re
import threading

logger = logging.getLogger(__name__)


class PIIRedactionService:
    """Boundary-aware PII masking applied to LLM inputs and outputs."""

    def __init__(self):
        self.patterns = {
            "ID_CARD": re.compile(r"(?<![\dXx])\d{17}[\dXx](?!\d)"),
            "PHONE": re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)"),
            "EMAIL": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
        }
        self._lock = threading.Lock()
        self.redacted_total = 0

    def redact(self, text: str) -> str:
        redacted_text = text
        hits = 0
        for label, pattern in self.patterns.items():
            redacted_text, count = pattern.subn(f"[{label}]", redacted_text)
            hits += count
        if hits:
            with self._lock:
                self.redacted_total += hits
            logger.info("pii redacted %s item(s)", hits)
        return redacted_text


pii_redactor = PIIRedactionService()

# Backwards-compatible alias
PIIRedactionMiddleware = PIIRedactionService
