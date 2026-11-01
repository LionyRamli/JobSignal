import pytest

from jobsignal.api import serve


@pytest.fixture
def runs(monkeypatch):
    calls = []
    monkeypatch.setattr(serve, "create_app", lambda: "app")
    monkeypatch.setattr(serve.uvicorn, "run", lambda app, **kw: calls.append((app, kw)))
    return calls


def test_non_loopback_requires_key(runs, monkeypatch, caplog):
    assert serve.main(["--host", "0.0.0.0"]) == 2  # noqa: S104 - the case under test
    assert runs == []
    monkeypatch.setenv("JOBSIGNAL_API_KEY", "k")
    assert serve.main(["--host", "0.0.0.0", "--port", "9000"]) == 0  # noqa: S104
    assert runs == [("app", {"host": "0.0.0.0", "port": 9000})]  # noqa: S104


@pytest.mark.parametrize("host", ["127.0.0.1", "::1", "localhost", "127.0.0.2"])
def test_loopback_hosts_accepted_without_key(runs, host):
    assert serve.main(["--host", host]) == 0
    assert runs[-1][1]["host"] == host


@pytest.mark.parametrize("host", ["192.168.1.10", "example.com", ""])
def test_other_hosts_need_a_key(runs, host):
    assert serve.main(["--host", host]) == 2


def test_default_is_localhost_8000(runs):
    assert serve.main([]) == 0
    assert runs == [("app", {"host": "127.0.0.1", "port": 8000})]
