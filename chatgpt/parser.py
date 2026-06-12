"""Parse structured ChatGPT responses."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.errors import ParseError
from src.utils import clean_text


@dataclass
class ParsedResponse:
    """Parsed connection request from ChatGPT."""

    connection_request: str = ""

    def is_valid(self) -> bool:
        return bool(self.connection_request and len(self.connection_request) <= 300)


def parse_chatgpt_response(raw_text: str) -> ParsedResponse:
    """Parse ChatGPT output for CONNECTION_REQUEST only."""
    if not raw_text or not raw_text.strip():
        raise ParseError("Empty ChatGPT response")

    text = raw_text.strip()
    result = ParsedResponse()

    pattern = re.compile(r"CONNECTION_REQUEST\s*:", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        raise ParseError("Response missing CONNECTION_REQUEST header")

    raw_value = text[match.end() :]
    extra = re.search(
        r"(?:^|\n)\s*(MESSAGE_1|MESSAGE_2|MESSAGE_3|LIKELY_CHALLENGE|WAVITY_USE_CASE|PERSONALIZATION_REASON)\s*:",
        raw_value,
        re.IGNORECASE,
    )
    if extra:
        raw_value = raw_value[: extra.start()]

    value = clean_text(raw_value)
    if not value:
        raise ParseError("CONNECTION_REQUEST field is empty")

    result.connection_request = value

    if not result.is_valid():
        raise ParseError(
            f"Invalid connection request (empty or >300 chars): {len(result.connection_request)} chars"
        )

    return result
