import sys
import tomllib

import pytest

from jobsignal.dashboard import serve
from tests.conftest import PROJECT_ROOT


@pytest.fixture
def launches():
    calls: list[list[str]] = []

    def run(argv: list[str]) -> int:
        calls.append(argv)
        return 0

    return calls, run


def flag(argv: list[str], name: str) -> str:
    return argv[argv.index(name) + 1]


def test_defaults_bind_loopback(launches):
    calls, run = launches
    assert serve.main([], run=run) == 0
    (argv,) = calls
    assert argv[:4] == [sys.executable, "-m", "streamlit", "run"]
    assert argv[4] == str(serve.APP_PATH)
    assert flag(argv, "--server.address") == "127.0.0.1"
    assert flag(argv, "--server.port") == "8501"
    assert flag(argv, "--server.headless") == "true"
    assert flag(argv, "--browser.gatherUsageStats") == "false"
    # pinned on the command line too: .streamlit/config.toml is only read from the cwd
    assert flag(argv, "--client.showErrorDetails") == "none"
    assert flag(argv, "--client.toolbarMode") == "viewer"


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com"])  # noqa: S104
def test_non_loopback_requires_allow_remote(launches, host, capsys):
    calls, run = launches
    assert serve.main(["--host", host], run=run) == 2
    assert calls == []
    assert "--allow-remote" in capsys.readouterr().err


def test_allow_remote_warns(launches, capsys):
    calls, run = launches
    assert serve.main(["--host", "0.0.0.0", "--port", "9000", "--allow-remote"], run=run) == 0  # noqa: S104
    assert flag(calls[0], "--server.address") == "0.0.0.0"  # noqa: S104
    assert (
        "WARNING: the dashboard has no login; anyone who can reach 0.0.0.0:9000 sees all data."
        in capsys.readouterr().err
    )


def test_launcher_returns_streamlit_exit_code():
    assert serve.main([], run=lambda argv: 3) == 3


def test_app_path_is_the_entry_point():
    assert serve.APP_PATH == PROJECT_ROOT / "dashboard" / "app.py"
    assert serve.APP_PATH.is_file()


def test_streamlit_config_pins_loopback_and_no_telemetry():
    config = tomllib.loads(
        (PROJECT_ROOT / ".streamlit" / "config.toml").read_text(encoding="utf-8")
    )
    assert config["server"]["address"] == "127.0.0.1"
    assert config["server"]["headless"] is True
    assert config["browser"]["gatherUsageStats"] is False
    assert config["client"]["showErrorDetails"] == "none"
