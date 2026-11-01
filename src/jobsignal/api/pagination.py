"""Opaque keyset-pagination cursors: urlsafe base64 of the last returned id."""

import base64
import binascii

INT64_MAX = 2**63 - 1  # SQLite INTEGER / PostgreSQL bigint
MAX_DIGITS = 19


def encode_cursor(last_id: int) -> str:
    return base64.urlsafe_b64encode(str(last_id).encode("ascii")).decode("ascii")


def decode_cursor(cursor: str) -> int:
    try:
        text = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("ascii")
    except (ValueError, binascii.Error, UnicodeError):
        raise ValueError("invalid cursor") from None
    if not (
        text.isascii()
        and text.isdigit()
        and 0 < len(text) <= MAX_DIGITS
        and 0 < int(text) <= INT64_MAX
    ):
        raise ValueError("invalid cursor")
    return int(text)
