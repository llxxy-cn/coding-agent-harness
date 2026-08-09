from service import health


def test_health():
    assert health() == "ok"
