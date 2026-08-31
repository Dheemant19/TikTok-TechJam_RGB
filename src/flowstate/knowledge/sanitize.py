from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from html.parser import HTMLParser

from flowstate.knowledge.models import SanitizedText

SANITIZER_VERSION = "1.0.0"
_BIDI = dict.fromkeys(map(ord, "\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069"), None)
_HIGH_RISK = {
    "override_rules": re.compile(r"\b(ignore|disregard|override)\b.{0,40}\b(instruction|rule|prompt|previous|prior)\b", re.I | re.S),
    "secret_request": re.compile(r"\b(reveal|print|send|exfiltrate|show)\b.{0,40}\b(secret|token|password|credential|api[ _-]?key)\b", re.I | re.S),
    "tool_invocation": re.compile(r"\b(call|invoke|execute|run)\b.{0,30}\b(tool|shell|command|terminal|function)\b", re.I | re.S),
}
_LOW_RISK = {
    "agent_address": re.compile(r"\b(assistant|agent|system prompt)\b", re.I),
    "instruction_language": re.compile(r"\b(you must|you should|do not|never)\b", re.I),
}


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.casefold(): (value or "").casefold() for key, value in attrs}
        style = attributes.get("style", "")
        hidden = tag.casefold() in {"script", "style", "noscript", "template"} or "hidden" in attributes
        hidden = hidden or "display:none" in style.replace(" ", "") or "visibility:hidden" in style.replace(" ", "")
        if hidden or self.hidden_depth:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            self.parts.append(data)


def _visible_text(value: str) -> str:
    if "<" not in value:
        return value
    parser = _VisibleTextParser()
    parser.feed(value)
    return " ".join(parser.parts)


def sanitize_text(value: str | None, maximum_characters: int = 20_000) -> SanitizedText:
    raw = value or ""
    raw_hash = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()
    visible = _visible_text(raw)
    normalized = unicodedata.normalize("NFKC", html.unescape(visible)).translate(_BIDI)
    normalized = "".join(char for char in normalized if char in "\n\t" or unicodedata.category(char) != "Cc")
    normalized = re.sub(r"[ \t]+", " ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    flags = [name for name, pattern in _HIGH_RISK.items() if pattern.search(normalized)]
    flags.extend(name for name, pattern in _LOW_RISK.items() if pattern.search(normalized))
    if len(normalized) > maximum_characters:
        normalized = normalized[:maximum_characters]
        flags.append("truncated")
    high_risk = any(flag in _HIGH_RISK for flag in flags)
    return SanitizedText(
        text=normalized,
        raw_content_hash=raw_hash,
        flags=list(dict.fromkeys(flags)),
        quarantined=high_risk,
        sanitizer_version=SANITIZER_VERSION,
    )
