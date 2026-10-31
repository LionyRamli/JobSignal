import io
import logging

import pytest

from jobsignal.logger import setup_logging


@pytest.fixture(autouse=True)
def reset_package_logger():
    yield
    pkg = logging.getLogger("jobsignal")
    for handler in list(pkg.handlers):
        pkg.removeHandler(handler)
    pkg.setLevel(logging.NOTSET)
    pkg.propagate = True


@pytest.fixture
def stream():
    return io.StringIO()


def test_module_logger_writes_level_name_and_message(stream):
    setup_logging("INFO", stream=stream)
    logging.getLogger("jobsignal.extraction.greenhouse").info("run started company=acme")

    line = stream.getvalue().strip()
    assert "INFO" in line
    assert "jobsignal.extraction.greenhouse" in line
    assert line.endswith("run started company=acme")


def test_messages_below_configured_level_are_dropped(stream):
    setup_logging("WARNING", stream=stream)
    log = logging.getLogger("jobsignal.extraction")
    log.info("routine run")
    log.warning("HTTP 429, backing off")

    output = stream.getvalue()
    assert "routine run" not in output
    assert "HTTP 429, backing off" in output


def test_level_defaults_to_settings(monkeypatch, stream):
    monkeypatch.setenv("JOBSIGNAL_LOG_LEVEL", "ERROR")
    setup_logging(stream=stream)
    log = logging.getLogger("jobsignal.extraction")
    log.warning("should be hidden")
    log.error("request failed")

    output = stream.getvalue()
    assert "should be hidden" not in output
    assert "request failed" in output


def test_repeated_setup_does_not_duplicate_output(stream):
    setup_logging("INFO", stream=stream)
    setup_logging("INFO", stream=stream)
    logging.getLogger("jobsignal").info("once")

    assert stream.getvalue().count("once") == 1


def test_repeated_setup_can_change_level(stream):
    setup_logging("ERROR", stream=stream)
    setup_logging("DEBUG", stream=stream)
    logging.getLogger("jobsignal").debug("now visible")

    assert "now visible" in stream.getvalue()


def test_third_party_loggers_are_not_captured(stream):
    setup_logging("DEBUG", stream=stream)
    logging.getLogger("urllib3.connectionpool").warning("noise from a library")

    assert "noise from a library" not in stream.getvalue()


def test_invalid_level_is_rejected(stream):
    with pytest.raises(ValueError, match="LOUD"):
        setup_logging("LOUD", stream=stream)
