"""The scrape CLI end-to-end over a mocked network and a real migrated SQLite file."""

import httpx
import pytest

from jobsignal.models import Posting
from jobsignal.scrape import main
from tests.conftest import PROJECT_ROOT

pytestmark = pytest.mark.integration

FIXTURE = (PROJECT_ROOT / "tests/fixtures/greenhouse/departments_anthropic.json").read_bytes()


def board_transport(requested):
    def handler(request):
        requested.append(request.url.path)
        if request.url.path == "/v1/boards/anthropic/departments":
            return httpx.Response(200, content=FIXTURE)
        if request.url.path == "/v1/boards/corrupt/departments":
            return httpx.Response(
                200, headers={"Content-Encoding": "gzip"}, content=iter([b"garbage"])
            )
        if request.url.path == "/v1/boards/nested/departments":
            return httpx.Response(200, content=b"[" * 100_000)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def read_postings(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    return [Posting.model_validate_json(line) for line in lines]


def test_writes_jsonl_per_posting(tmp_path, migrated_url):
    out = tmp_path / "raw" / "run.jsonl"
    requested = []

    code = main(
        ["anthropic", "--out", str(out)], transport=board_transport(requested), min_interval=0
    )

    assert code == 0
    postings = read_postings(out)
    assert len(postings) == 6
    assert {p.company for p in postings} == {"anthropic"}
    assert requested == ["/v1/boards/anthropic/departments"]


def test_one_failing_company_does_not_stop_others(tmp_path, capsys, migrated_url):
    out = tmp_path / "run.jsonl"
    requested = []

    code = main(
        ["nosuchboard", "../evil", "anthropic", "--out", str(out)],
        transport=board_transport(requested),
        min_interval=0,
    )

    assert code == 1
    assert {p.company for p in read_postings(out)} == {"anthropic"}
    assert requested == ["/v1/boards/nosuchboard/departments", "/v1/boards/anthropic/departments"]
    stderr = capsys.readouterr().err
    assert "ERROR" in stderr
    assert "nosuchboard" in stderr
    assert "../evil" in stderr


def test_jsonl_written_only_with_out(tmp_path, migrated_url):
    code = main(["anthropic"], transport=board_transport([]), min_interval=0)

    assert code == 0
    assert not (tmp_path / "data").exists()
    assert list(tmp_path.glob("**/*.jsonl")) == []


def test_undecodable_responses_fail_their_company_only(tmp_path, migrated_url):
    out = tmp_path / "run.jsonl"
    code = main(
        ["corrupt", "nested", "anthropic", "--out", str(out)],
        transport=board_transport([]),
        min_interval=0,
    )
    assert code == 1
    assert len(read_postings(out)) == 6
