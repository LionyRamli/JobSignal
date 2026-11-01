import pytest
from pydantic import ValidationError

from jobsignal.config import get_settings


def test_defaults_target_local_sqlite_and_info_logging():
    settings = get_settings()
    assert settings.database_url == "sqlite:///jobsignal.db"
    assert settings.log_level == "INFO"


def test_env_vars_override_defaults(monkeypatch):
    monkeypatch.setenv("JOBSIGNAL_DATABASE_URL", "postgresql+psycopg://u@localhost/js")
    monkeypatch.setenv("JOBSIGNAL_LOG_LEVEL", "debug")
    settings = get_settings()
    assert settings.database_url == "postgresql+psycopg://u@localhost/js"
    assert settings.log_level == "DEBUG"


def test_dotenv_file_is_read_from_working_directory(tmp_path):
    (tmp_path / ".env").write_text("JOBSIGNAL_LOG_LEVEL=WARNING\n")
    assert get_settings().log_level == "WARNING"


@pytest.mark.parametrize("bad_level", ["LOUD", "", "10"])
def test_unknown_log_level_is_rejected(monkeypatch, bad_level):
    monkeypatch.setenv("JOBSIGNAL_LOG_LEVEL", bad_level)
    with pytest.raises(ValidationError):
        get_settings()


@pytest.mark.parametrize("bad_url", ["", "   "])
def test_blank_database_url_is_rejected(monkeypatch, bad_url):
    monkeypatch.setenv("JOBSIGNAL_DATABASE_URL", bad_url)
    with pytest.raises(ValidationError):
        get_settings()


def test_api_url_default_and_normalisation(monkeypatch):
    assert get_settings().api_url == "http://127.0.0.1:8000"
    monkeypatch.setenv("JOBSIGNAL_API_URL", " https://x.example/ ")
    assert get_settings().api_url == "https://x.example"


@pytest.mark.parametrize("bad", ["ftp://x", "javascript:alert(1)", "127.0.0.1:8000", ""])
def test_api_url_must_be_http(monkeypatch, bad):
    monkeypatch.setenv("JOBSIGNAL_API_URL", bad)
    with pytest.raises(ValidationError):
        get_settings()
