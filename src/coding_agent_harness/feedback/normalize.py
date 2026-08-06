from __future__ import annotations

import re


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_DURATION = re.compile(r"\b\d+(?:\.\d+)?s\b")
_TEMP = re.compile(r"(?i)(?:[A-Z]:\\[^\s]+|/(?:tmp|private/tmp)/[^\s]+)")


def normalize_summary(value: str, *, limit: int = 2000) -> str:
    value = _ANSI.sub("", value).replace("\r", " ").replace("\n", " ")
    value = _DURATION.sub("<duration>", value)
    value = _TEMP.sub("<path>", value)
    value = " ".join(value.split())
    return (value or "pytest result unavailable")[:limit]
