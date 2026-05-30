from __future__ import annotations

import domoxml


def test_version_is_exposed() -> None:
    assert isinstance(domoxml.__version__, str)
    assert domoxml.__version__
