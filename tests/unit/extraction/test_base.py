import pytest

from jobsignal.extraction.base import ATSSource, FetchResult
from jobsignal.extraction.errors import (
    ExtractionError,
    InvalidPayloadError,
    ResponseTooLargeError,
    RetryExhaustedError,
    SourceNotFoundError,
)


def test_atssource_cannot_be_instantiated():
    with pytest.raises(TypeError):
        ATSSource()


def test_subclass_without_fetch_fails():
    class Incomplete(ATSSource):
        name = "incomplete"

    with pytest.raises(TypeError):
        Incomplete()


def test_complete_subclass_can_be_instantiated():
    class Complete(ATSSource):
        name = "complete"

        def fetch(self, company):
            return FetchResult([], skipped=2)

    assert Complete().fetch_postings("acme") == []
    assert Complete().fetch("acme").complete is False
    assert FetchResult([]).complete is True


@pytest.mark.parametrize(
    "error",
    [
        SourceNotFoundError("x"),
        RetryExhaustedError(503),
        ResponseTooLargeError("x"),
        InvalidPayloadError("x"),
    ],
)
def test_errors_share_base(error):
    assert isinstance(error, ExtractionError)


def test_retry_exhausted_keeps_last_status():
    assert RetryExhaustedError(503).last_status == 503
    assert RetryExhaustedError(None).last_status is None
