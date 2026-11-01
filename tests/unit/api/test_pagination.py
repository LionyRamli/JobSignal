import pytest

from jobsignal.api.pagination import decode_cursor, encode_cursor


@pytest.mark.parametrize("last_id", [1, 42, 10**12])
def test_cursor_round_trip(last_id):
    assert decode_cursor(encode_cursor(last_id)) == last_id


@pytest.mark.parametrize("bad", ["", "abc", "LTE=", "MA==", "!!!", "AAAA" * 50, "MS41"])
def test_cursor_rejects_garbage(bad):
    with pytest.raises(ValueError, match="cursor"):
        decode_cursor(bad)
