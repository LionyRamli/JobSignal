"""Errors raised by ATS sources and the shared HTTP client."""


class ExtractionError(Exception):
    """Base class for every extraction failure."""


class SourceNotFoundError(ExtractionError):
    """The board/company does not exist on this ATS (HTTP 404)."""


class RetryExhaustedError(ExtractionError):
    """All retry attempts failed; ``last_status`` is None for network errors."""

    def __init__(self, last_status: int | None, message: str = "") -> None:
        self.last_status = last_status
        super().__init__(message or f"retries exhausted (last status: {last_status})")


class ResponseTooLargeError(ExtractionError):
    """The response body exceeded the configured size cap."""


class InvalidPayloadError(ExtractionError):
    """The response was not the JSON shape the source expects."""
