from neuropilot_core import health


def test_health() -> None:
    assert health() == "ok"
