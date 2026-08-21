"""Normalize resident response values across legacy and canonical records."""

from __future__ import annotations


_CANONICAL_RESPONSES = {
    "HELP": "resident_response_help",
    "STABLE": "resident_response_stable",
    "RESIDENT_RESPONSE_HELP": "resident_response_help",
    "RESIDENT_RESPONSE_STABLE": "resident_response_stable",
}


def canonical_resident_response(value: str | None) -> str | None:
    if not value:
        return None
    return _CANONICAL_RESPONSES.get(value.strip().upper())
