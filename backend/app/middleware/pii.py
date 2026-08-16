import re


class PIIRedactionMiddleware:
    def __init__(self):
        # Simple regex patterns for demo
        self.patterns = {
            "ID_CARD": r"\d{17}[\dXx]",
            "PHONE": r"1[3-9]\d{9}",
            "EMAIL": r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
        }

    def redact(self, text: str) -> str:
        redacted_text = text
        for label, pattern in self.patterns.items():
            redacted_text = re.sub(pattern, f"[{label}]", redacted_text)
        return redacted_text

pii_redactor = PIIRedactionMiddleware()
