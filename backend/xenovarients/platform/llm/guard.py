"""Prompt construction that keeps retrieved content untrusted."""

import re

_DIRECT_IDENTIFIER = re.compile(
    r"(?:\b[\w.+-]+@[\w-]+\.[\w.-]+\b|(?<!\w)\+?\d[\d\s().-]{7,}\d)",
    re.IGNORECASE,
)


def redact_direct_identifiers(text: str) -> str:
    """Mask email addresses and phone-like values before model calls."""
    return _DIRECT_IDENTIFIER.sub("[REDACTED]", text)


def build_prompt(system: str, user: str, retrieved: list[str]) -> list[dict[str, str]]:
    """Build a prompt with retrieved records explicitly marked as data."""
    context = "\n\n".join(
        f"<retrieved-data>\n{redact_direct_identifiers(item)}\n</retrieved-data>"
        for item in retrieved
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"{user}\n\nRetrieved data (untrusted):\n{context}"},
    ]
